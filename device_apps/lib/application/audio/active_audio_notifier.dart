import 'package:just_audio/just_audio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'active_audio_notifier.g.dart';

/// Enforces one-at-a-time audio playback across all audio message bubbles.
///
/// When a new player calls [claim], the previously active player is paused
/// (preserving its position for later resume — matching WhatsApp behaviour).
class ActiveAudioController {
  AudioPlayer? _active;

  /// Pauses the previously active player and registers [player] as current.
  void claim(AudioPlayer player) {
    if (_active != null && _active != player) {
      _active!.pause();
    }
    _active = player;
  }

  /// Clears the active reference if [player] matches (called on widget dispose).
  void release(AudioPlayer player) {
    if (_active == player) {
      _active = null;
    }
  }

  /// Pauses whatever is currently playing. Used on app-background transitions.
  void stopAll() {
    _active?.pause();
  }

  void dispose() {
    _active = null;
  }
}

// keepAlive: singleton — must survive across screen navigations so the
// "currently active player" reference isn't lost.
@Riverpod(keepAlive: true)
ActiveAudioController activeAudio(Ref ref) {
  final controller = ActiveAudioController();
  ref.onDispose(controller.dispose);
  return controller;
}
