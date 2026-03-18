import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/services/audio_recording_service.dart';
import '../../platform/media/audio_recorder_impl.dart';

export '../../domain/services/audio_recording_service.dart'
    show AudioRecordingResult;

part 'recording_notifier.g.dart';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

sealed class RecordingState {
  const RecordingState();
}

/// Mic is idle. [webPermissionGranted] reflects browser mic access on web;
/// always true on mobile (the OS dialog fires during startRecording).
final class RecordingIdle extends RecordingState {
  const RecordingIdle({this.webPermissionGranted = false});

  final bool webPermissionGranted;
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
  const RecordingCompleted({
    this.result,
    this.webPermissionGranted = false,
  });

  final AudioRecordingResult? result;
  final bool webPermissionGranted;
}

// ---------------------------------------------------------------------------
// Notifier
// ---------------------------------------------------------------------------

// keepAlive: owns the AudioRecorder which must not be disposed mid-session.
@Riverpod(keepAlive: true)
class RecordingNotifier extends _$RecordingNotifier {
  late AudioRecorder _recorder;
  Timer? _timer;
  bool _webPermissionGranted = !kIsWeb;

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
    if (kIsWeb) unawaited(_checkPermissionSilently());
    return RecordingIdle(webPermissionGranted: _webPermissionGranted);
  }

  // ---------------------------------------------------------------------------
  // Permission (web only)
  // ---------------------------------------------------------------------------

  Future<void> _checkPermissionSilently() async {
    try {
      final granted = await _recorder.hasPermission();
      _webPermissionGranted = granted;
      if (granted && state is RecordingIdle) {
        state = const RecordingIdle(webPermissionGranted: true);
      }
    } catch (_) {
      // Permission API unavailable — ignored, user will tap to grant.
    }
  }

  /// Triggers the browser permission dialog on web. Returns true if granted.
  /// No-op on mobile (permission is handled during [startRecording]).
  Future<bool> ensureWebPermission() async {
    if (!kIsWeb || _webPermissionGranted) return true;
    try {
      final granted = await _recorder.hasPermission();
      _webPermissionGranted = granted;
      if (state is RecordingIdle) {
        state = RecordingIdle(webPermissionGranted: granted);
      }
      return granted;
    } catch (_) {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // Recording lifecycle
  // ---------------------------------------------------------------------------

  /// Starts recording. Throws if mic permission is denied or the recorder
  /// fails to start. The caller should catch and surface the error.
  Future<void> startRecording() async {
    if (state is! RecordingIdle) return;
    await _recorder.startRecording();
    _webPermissionGranted = true;
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
    state = RecordingCompleted(
      result: result,
      webPermissionGranted: _webPermissionGranted,
    );
  }

  /// Stops recording and returns the captured audio. Returns null if not
  /// currently recording (e.g. already auto-stopped).
  Future<AudioRecordingResult?> stopRecording() async {
    if (state is! RecordingActive) return null;
    _cleanupTimer();
    // Set state synchronously before the async gap so concurrent calls (e.g.
    // from _onLongPressMoveUpdate firing while the await is in progress) see
    // RecordingIdle immediately and return early — preventing re-entry.
    state = RecordingIdle(webPermissionGranted: _webPermissionGranted);
    return await _recorder.stopRecording();
  }

  /// Cancels the current recording, discarding all captured audio.
  Future<void> cancelRecording() async {
    if (state is! RecordingActive) return;
    _cleanupTimer();
    // Set state synchronously before the async gap — same re-entry guard as
    // stopRecording(); _onLongPressMoveUpdate fires on every pointer event
    // while sliding, so multiple concurrent cancelRecording() calls are common.
    state = RecordingIdle(webPermissionGranted: _webPermissionGranted);
    await _recorder.cancelRecording();
  }

  /// Called by the widget after it has handled a [RecordingCompleted] state,
  /// returning the notifier to [RecordingIdle].
  void acknowledgeCompleted() {
    if (state is RecordingCompleted) {
      state = RecordingIdle(webPermissionGranted: _webPermissionGranted);
    }
  }

  void _cleanupTimer() {
    _timer?.cancel();
    _timer = null;
    _recorder.isRecording.removeListener(_onServiceStop);
  }
}
