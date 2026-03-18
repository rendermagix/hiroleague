import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueNotifier;

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

  Future<bool> hasPermission();

  Future<void> startRecording();

  Future<AudioRecordingResult?> stopRecording();

  Future<void> cancelRecording();

  void dispose();
}
