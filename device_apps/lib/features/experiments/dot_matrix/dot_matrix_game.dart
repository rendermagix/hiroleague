import 'package:flame/game.dart';
import 'package:flutter/painting.dart';

import 'dot_matrix_component.dart';
import 'dot_matrix_config.dart';

// ---------------------------------------------------------------------------
// Demo word list — edit freely.
// ---------------------------------------------------------------------------

const List<String> _demoWords = [
  'HIRO',
  'HELLO',
  'WORLD',
  'FLAME',
  'FLUTTER',
  'CONNECT',
  'SECURE',
  'CHAT',
  'SIGNAL',
  'LEAGUE',
];

// ---------------------------------------------------------------------------
// DotMatrixGame
// ---------------------------------------------------------------------------

/// A [FlameGame] that hosts a [DotMatrixComponent] and cycles through
/// [_demoWords], showing each word for [DotMatrixConfig.showDuration] seconds,
/// then hiding it for [DotMatrixConfig.pauseDuration] seconds before showing
/// the next word.
///
/// Embed via [GameWidget] in the Flutter widget tree.
class DotMatrixGame extends FlameGame {
  DotMatrixGame({DotMatrixConfig? config})
      : _config = config ?? const DotMatrixConfig();

  DotMatrixConfig _config;

  late DotMatrixComponent _dots;

  int _wordIndex = 0;

  /// true  = word is currently displayed; timer counts down [showDuration].
  /// false = blank pause; timer counts down [pauseDuration].
  bool _showing = false;

  double _elapsed = 0.0;

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  @override
  Color backgroundColor() => _config.backgroundColor;

  @override
  Future<void> onLoad() async {
    _dots = DotMatrixComponent(
      config: _config,
      initialText: _currentWord,
    )..setVisible(false);

    // The component always sits at the origin and fills the full canvas.
    // Centering of the text within the grid is handled inside the component.
    _dots.position = Vector2.zero();
    _dots.setCanvasSize(size);

    add(_dots);
  }

  @override
  void onGameResize(Vector2 size) {
    super.onGameResize(size);
    if (isLoaded) _dots.setCanvasSize(size);
  }

  // ---------------------------------------------------------------------------
  // Game loop
  // ---------------------------------------------------------------------------

  @override
  void update(double dt) {
    super.update(dt);
    _elapsed += dt;

    if (_showing) {
      if (_elapsed >= _config.showDuration) {
        _elapsed = 0.0;
        _showing = false;
        _dots.setVisible(false);
      }
    } else {
      if (_elapsed >= _config.pauseDuration) {
        _elapsed = 0.0;
        _wordIndex = (_wordIndex + 1) % _demoWords.length;
        _dots.setText(_currentWord);
        _showing = true;
        _dots.setVisible(true);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /// Replace the active configuration at runtime. Immediately re-renders with
  /// the new colors, sizes, timing, and pulse values.
  void updateConfig(DotMatrixConfig config) {
    _config = config;
    _dots.config = config;
    _dots.setCanvasSize(size);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  String get _currentWord => _demoWords[_wordIndex];
}
