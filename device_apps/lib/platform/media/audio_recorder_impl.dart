import 'dart:async';
import 'dart:io';

import 'package:app_settings/app_settings.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart' as rec;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/services/audio_recording_service.dart';
import 'has_mic_device.dart' as mic_detect;

part 'audio_recorder_impl.g.dart';

/// Concrete [AudioRecorder] backed by the `record` package.
///
/// Records in AAC/m4a format (~128 kbps), accepted by both OpenAI and Gemini
/// STT APIs. Enforces a 60-second maximum and auto-stops when reached.
///
/// Platform behaviour:
/// - Mobile (iOS/Android): records to a temp file in the system temp dir.
/// - Web: records to in-memory bytes via MediaRecorder.
class AudioRecorderImpl implements AudioRecorder {
  AudioRecorderImpl() : _recorder = rec.AudioRecorder();

  final rec.AudioRecorder _recorder;

  @override
  final ValueNotifier<bool> isRecording = ValueNotifier(false);

  DateTime? _startTime;
  Timer? _maxTimer;
  Completer<AudioRecordingResult?>? _autoStopCompleter;

  static const int _maxDurationMs = 60000;

  // Cached after the first probe so subsequent recordings skip the async
  // isEncoderSupported() round-trips (codec support doesn't change mid-session).
  rec.AudioEncoder? _cachedEncoder;

  @override
  Future<MicPermissionStatus> checkPermissionStatus() async {
    final granted = await _recorder.hasPermission(request: false);
    return granted ? MicPermissionStatus.granted : MicPermissionStatus.denied;
  }

  @override
  Future<MicPermissionStatus> requestPermission() async {
    final granted = await _recorder.hasPermission(request: true);
    return granted ? MicPermissionStatus.granted : MicPermissionStatus.denied;
  }

  @override
  Future<void> openPermissionSettings() async {
    if (kIsWeb) return;
    AppSettings.openAppSettings();
  }

  @override
  Future<bool> hasMicrophoneDevice() => mic_detect.hasMicDevice();

  /// Returns the best supported encoder for the current platform.
  ///
  /// On web, MediaRecorder MIME-type support varies by browser:
  ///   - opus (webm/opus)  → Chrome, Firefox, Edge
  ///   - aacLc (mp4/aac)  → Chrome, Safari (NOT Firefox)
  ///   - wav               → universal fallback (large files)
  /// We probe in preference order so the most efficient supported codec wins.
  Future<rec.AudioEncoder> _chooseEncoder() async {
    if (_cachedEncoder != null) return _cachedEncoder!;
    if (!kIsWeb) {
      _cachedEncoder = rec.AudioEncoder.aacLc;
      return _cachedEncoder!;
    }
    for (final encoder in const [
      rec.AudioEncoder.opus,
      rec.AudioEncoder.aacLc,
      rec.AudioEncoder.wav,
    ]) {
      if (await _recorder.isEncoderSupported(encoder)) {
        _cachedEncoder = encoder;
        return encoder;
      }
    }
    _cachedEncoder = rec.AudioEncoder.opus; // should never reach here
    return _cachedEncoder!;
  }

  @override
  Future<void> startRecording() async {
    // Permission is already verified by the UI layer (RecordingNotifier /
    // MessageInputBar) before reaching here — skip the redundant async
    // round-trip to keep recording start snappy.

    final encoder = await _chooseEncoder();
    final config = rec.RecordConfig(
      encoder: encoder,
      bitRate: 128000,
      sampleRate: 44100,
    );

    try {
      if (kIsWeb) {
        // Path is only used as a download filename on web; content type is
        // determined by the encoder, not the extension.
        await _recorder.start(config, path: 'audio');
      } else {
        final tmpDir = await getTemporaryDirectory();
        final path =
            '${tmpDir.path}/hiro_rec_${DateTime.now().millisecondsSinceEpoch}.m4a';
        await _recorder.start(config, path: path);
      }
    } catch (e) {
      // Normalise browser permission denial into a readable message.
      final msg = e.toString().toLowerCase();
      if (msg.contains('permission') ||
          msg.contains('notallowed') ||
          msg.contains('denied')) {
        throw Exception('Microphone permission denied');
      }
      rethrow;
    }

    _startTime = DateTime.now();
    isRecording.value = true;

    _autoStopCompleter = Completer<AudioRecordingResult?>();
    _maxTimer = Timer(const Duration(milliseconds: _maxDurationMs), () async {
      if (isRecording.value) {
        isRecording.value = false;
        final result = await _doStop();
        _safeCompleteAutoStop(result);
      }
    });
  }

  @override
  int get elapsedMs => _startTime != null
      ? DateTime.now().difference(_startTime!).inMilliseconds
      : 0;

  @override
  Future<AudioRecordingResult?> stopRecording() async {
    if (!isRecording.value) return null;
    // Mark stopped synchronously so concurrent calls return early (prevents
    // "Bad state: Future already completed" from _autoStopCompleter).
    isRecording.value = false;
    _maxTimer?.cancel();
    _safeCompleteAutoStop(null);
    return _doStop();
  }

  @override
  Future<void> cancelRecording() async {
    if (!isRecording.value) return;
    // Mark stopped synchronously — cancelRecording() can be called on every
    // pointer-move event while sliding, so without this guard the Completer
    // throws "Bad state: Future already completed" on the second concurrent call.
    isRecording.value = false;
    _maxTimer?.cancel();
    _safeCompleteAutoStop(null);

    final path = await _recorder.stop();
    _startTime = null;

    if (path != null && path.isNotEmpty && !kIsWeb) {
      final file = File(path);
      if (await file.exists()) await file.delete();
    }
  }

  /// Completes [_autoStopCompleter] exactly once, then nulls it out.
  void _safeCompleteAutoStop(AudioRecordingResult? result) {
    final c = _autoStopCompleter;
    if (c != null && !c.isCompleted) c.complete(result);
    _autoStopCompleter = null;
  }

  Future<AudioRecordingResult?> _doStop() async {
    final durationMs = elapsedMs;
    final path = await _recorder.stop();
    _startTime = null;

    if (kIsWeb) {
      return AudioRecordingResult(
        bytes: Uint8List(0),
        durationMs: durationMs,
        tempPath: path ?? '',
      );
    }

    if (path == null || path.isEmpty) return null;
    final file = File(path);
    if (!await file.exists()) return null;
    final bytes = await file.readAsBytes();
    return AudioRecordingResult(
      bytes: bytes,
      durationMs: durationMs,
      tempPath: path,
    );
  }

  @override
  void dispose() {
    _maxTimer?.cancel();
    _recorder.dispose();
    isRecording.dispose();
  }
}

/// Provides the platform-specific [AudioRecorder] implementation.
/// keepAlive: false — RecordingNotifier creates/disposes its own instance.
@riverpod
AudioRecorder audioRecorder(Ref ref) {
  final recorder = AudioRecorderImpl();
  ref.onDispose(recorder.dispose);
  return recorder;
}
