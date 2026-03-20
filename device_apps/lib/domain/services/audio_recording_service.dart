import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueNotifier;

/// Mic permission status returned by [AudioRecorder.checkPermissionStatus]
/// and [AudioRecorder.requestPermission].
enum MicPermissionStatus { granted, denied }

/// Result returned from [AudioRecorder.stopRecording].
class AudioRecordingResult {
  const AudioRecordingResult({
    required this.bytes,
    required this.durationMs,
    required this.tempPath,
  });

  final Uint8List bytes;
  final int durationMs;

  /// Temporary file path (mobile) or blob URL (web — bytes are in memory).
  final String tempPath;
}

/// Pure-Dart contract for audio recording — no Flutter/platform imports.
///
/// The concrete implementation lives in `platform/media/` and wraps the
/// `record` package. This interface keeps `domain/` free of third-party
/// dependencies per the architecture doc.
abstract class AudioRecorder {
  ValueNotifier<bool> get isRecording;

  int get elapsedMs;

  /// Checks mic permission without triggering the OS/browser dialog.
  Future<MicPermissionStatus> checkPermissionStatus();

  /// Requests mic permission, showing the OS/browser dialog if applicable.
  Future<MicPermissionStatus> requestPermission();

  /// Opens device settings so the user can grant mic permission manually.
  /// No-op on web (browser permissions can't be opened programmatically).
  Future<void> openPermissionSettings();

  /// Returns true if the device has at least one audio input (microphone).
  /// On mobile this always returns true; on web it probes via the browser
  /// MediaDevices API.
  Future<bool> hasMicrophoneDevice();

  Future<void> startRecording();

  Future<AudioRecordingResult?> stopRecording();

  Future<void> cancelRecording();

  void dispose();
}
