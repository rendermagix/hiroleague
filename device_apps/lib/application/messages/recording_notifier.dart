import 'dart:async';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/services/audio_recording_service.dart';
import '../../platform/media/audio_recorder_impl.dart';

export '../../domain/services/audio_recording_service.dart'
    show AudioRecordingResult, MicPermissionStatus;

part 'recording_notifier.g.dart';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

sealed class RecordingState {
  const RecordingState();
}

/// Mic is idle. [micPermissionGranted] reflects whether mic access has been
/// granted on the current platform (Android, iOS, or web).
final class RecordingIdle extends RecordingState {
  const RecordingIdle({
    this.micPermissionGranted = false,
    this.previouslyDenied = false,
    this.hasMicrophone = true,
  });

  final bool micPermissionGranted;

  /// True after the user has denied at least once. The UI uses this to offer
  /// "Open Settings" alongside "Try Again" in the permission dialog.
  final bool previouslyDenied;

  /// False when no audio input hardware is detected (e.g. desktop with no mic).
  final bool hasMicrophone;
}

/// Actively recording. [elapsedSeconds] drives the UI timer label.
final class RecordingActive extends RecordingState {
  const RecordingActive({required this.elapsedSeconds});

  final int elapsedSeconds;
}

/// Auto-stopped when the 60-second timer fires. The widget must consume
/// [result] then call [RecordingNotifier.acknowledgeCompleted] to return
/// to [RecordingIdle].
final class RecordingCompleted extends RecordingState {
  const RecordingCompleted({this.result});

  final AudioRecordingResult? result;
}

// ---------------------------------------------------------------------------
// Notifier
// ---------------------------------------------------------------------------

// keepAlive: owns the AudioRecorder which must not be disposed mid-session.
@Riverpod(keepAlive: true)
class RecordingNotifier extends _$RecordingNotifier {
  late AudioRecorder _recorder;
  Timer? _timer;
  bool _micPermissionGranted = false;
  bool _previouslyDenied = false;
  bool _hasMicrophone = true;

  @override
  RecordingState build() {
    // ref.watch (not ref.read) keeps audioRecorderProvider alive for the full
    // lifetime of this notifier. ref.read had no listener, causing Riverpod to
    // auto-dispose the provider immediately after build() returned — which
    // called recorder.dispose() — making every subsequent recording call throw
    // "Record has not yet been created or has already been disposed."
    _recorder = ref.watch(audioRecorderProvider);
    ref.onDispose(() {
      _timer?.cancel();
      // audioRecorderProvider owns _recorder and disposes it via its own
      // ref.onDispose — do not call _recorder.dispose() here (double-dispose).
    });
    unawaited(_probeHardwareAndPermission());
    return _buildIdle();
  }

  // ---------------------------------------------------------------------------
  // Permission & hardware detection (all platforms)
  // ---------------------------------------------------------------------------

  RecordingIdle _buildIdle() => RecordingIdle(
        micPermissionGranted: _micPermissionGranted,
        previouslyDenied: _previouslyDenied,
        hasMicrophone: _hasMicrophone,
      );

  Future<void> _probeHardwareAndPermission() async {
    try {
      _hasMicrophone = await _recorder.hasMicrophoneDevice();
      if (!_hasMicrophone) {
        if (state is RecordingIdle) state = _buildIdle();
        return;
      }
      final status = await _recorder.checkPermissionStatus();
      _micPermissionGranted = status == MicPermissionStatus.granted;
      if (state is RecordingIdle) state = _buildIdle();
    } catch (_) {
      // API unavailable — ignored, user will tap to grant.
    }
  }

  /// Requests mic permission (triggers the OS/browser dialog on first ask).
  /// Returns the resulting [MicPermissionStatus].
  Future<MicPermissionStatus> ensurePermission() async {
    if (_micPermissionGranted) return MicPermissionStatus.granted;
    try {
      final status = await _recorder.requestPermission();
      _micPermissionGranted = status == MicPermissionStatus.granted;
      if (!_micPermissionGranted) _previouslyDenied = true;
      if (state is RecordingIdle) state = _buildIdle();
      return status;
    } catch (_) {
      _previouslyDenied = true;
      return MicPermissionStatus.denied;
    }
  }

  /// Opens device settings so the user can grant mic permission manually.
  Future<void> openPermissionSettings() => _recorder.openPermissionSettings();

  // ---------------------------------------------------------------------------
  // Recording lifecycle
  // ---------------------------------------------------------------------------

  /// Starts recording. Throws if mic permission is denied or the recorder
  /// fails to start. The caller should catch and surface the error.
  Future<void> startRecording() async {
    if (state is! RecordingIdle) return;
    await _recorder.startRecording();
    state = const RecordingActive(elapsedSeconds: 0);
    _timer = Timer.periodic(const Duration(seconds: 1), _onTick);
    _recorder.isRecording.addListener(_onServiceStop);
  }

  void _onTick(Timer _) {
    if (state is! RecordingActive) return;
    final elapsed = _recorder.elapsedMs ~/ 1000;
    if (elapsed >= 60) {
      unawaited(_autoStop());
      return;
    }
    state = RecordingActive(elapsedSeconds: elapsed);
  }

  void _onServiceStop() {
    if (!_recorder.isRecording.value && state is RecordingActive) {
      unawaited(_autoStop());
    }
  }

  Future<void> _autoStop() async {
    if (state is! RecordingActive) return;
    _cleanupTimer();
    final result = await _recorder.stopRecording();
    state = RecordingCompleted(result: result);
  }

  /// Stops recording and returns the captured audio. Returns null if not
  /// currently recording (e.g. already auto-stopped).
  Future<AudioRecordingResult?> stopRecording() async {
    if (state is! RecordingActive) return null;
    _cleanupTimer();
    // Set state synchronously before the async gap so concurrent calls (e.g.
    // from _onLongPressMoveUpdate firing while the await is in progress) see
    // RecordingIdle immediately and return early — preventing re-entry.
    state = _buildIdle();
    return await _recorder.stopRecording();
  }

  /// Cancels the current recording, discarding all captured audio.
  Future<void> cancelRecording() async {
    if (state is! RecordingActive) return;
    _cleanupTimer();
    // Set state synchronously before the async gap — same re-entry guard as
    // stopRecording(); _onLongPressMoveUpdate fires on every pointer event
    // while sliding, so multiple concurrent cancelRecording() calls are common.
    state = _buildIdle();
    await _recorder.cancelRecording();
  }

  /// Called by the widget after it has handled a [RecordingCompleted] state,
  /// returning the notifier to [RecordingIdle].
  void acknowledgeCompleted() {
    if (state is RecordingCompleted) state = _buildIdle();
  }

  void _cleanupTimer() {
    _timer?.cancel();
    _timer = null;
    _recorder.isRecording.removeListener(_onServiceStop);
  }
}
