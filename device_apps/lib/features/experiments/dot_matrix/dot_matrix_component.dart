import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flame/components.dart';
import 'package:flutter/painting.dart';

import 'bitmap_font.dart';
import 'dot_matrix_config.dart';

/// A Flame [PositionComponent] that renders a dot matrix display.
///
/// The component fills its [size] (set by [DotMatrixGame] to the full canvas)
/// with a faint background grid of off-dots. The text is converted to lit
/// on-dots and rendered centred within that grid.
///
/// The glow breathes each frame via a sine-wave driven by [DotMatrixConfig.pulseSpeed]
/// and [DotMatrixConfig.pulseAmplitude]. Set [pulseSpeed] to 0 for a static glow.
///
/// Call [setText] to change the displayed string at any time.
/// Call [setVisible] to show or hide all lit dots (the off-dot grid always stays).
class DotMatrixComponent extends PositionComponent {
  DotMatrixComponent({
    required DotMatrixConfig config,
    String initialText = '',
  })  : _config = config,
        _text = initialText;

  DotMatrixConfig _config;
  String _text;
  bool _visible = true;

  // Sine-wave time accumulator for the glow pulse.
  double _time = 0.0;

  // Text dot grid: [row][col] = true means lit.
  List<List<bool>> _textGrid = [];

  // Full-canvas grid dimensions (how many dot columns/rows fill the widget).
  int _canvasCols = 0;
  int _canvasRows = 0;

  // Pixel origin of the full dot grid inside the component (centres the grid).
  double _gridOriginX = 0.0;
  double _gridOriginY = 0.0;

  // Dot-grid column/row where the text block starts (for centering text).
  int _textStartCol = 0;
  int _textStartRow = 0;

  // Cached paints, rebuilt on config change.
  late Paint _offPaint;
  late Paint _gapPaint; // background-coloured lines punched through lit dots

  @override
  Future<void> onLoad() async {
    _rebuildPaints();
    _rebuildLayout();
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  DotMatrixConfig get config => _config;

  set config(DotMatrixConfig value) {
    _config = value;
    _rebuildPaints();
    _rebuildLayout();
  }

  String get text => _text;

  void setText(String value) {
    if (_text == value) return;
    _text = value;
    _rebuildLayout();
  }

  bool get isVisible => _visible;

  void setVisible(bool value) {
    _visible = value;
    // Reset the pulse cycle so every word starts its glow breath from the
    // same phase (sin(0) = 0 → ramps up immediately from base values).
    if (value) _time = 0.0;
  }

  /// Called by the game whenever the canvas size changes so the background
  /// grid always fills the full widget area.
  void setCanvasSize(Vector2 canvasSize) {
    size = canvasSize;
    _rebuildLayout();
  }

  // ---------------------------------------------------------------------------
  // Game loop
  // ---------------------------------------------------------------------------

  @override
  void update(double dt) {
    super.update(dt);
    _time += dt;
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  @override
  void render(Canvas canvas) {
    final stride = _config.dotStride;
    final halfW = _config.dotWidth / 2;
    final halfH = _config.dotHeight / 2;
    final baseR = (halfW > halfH ? halfW : halfH) * _config.glowRadius;

    final speed = _config.pulseSpeed;
    final amplitude = _config.pulseAmplitude;

    // Draw every dot in the full canvas grid.
    for (var row = 0; row < _canvasRows; row++) {
      for (var col = 0; col < _canvasCols; col++) {
        final cx = _gridOriginX + col * stride + halfW;
        final cy = _gridOriginY + row * stride + halfH;

        // Per-dot phase offset derived from grid position — no storage needed.
        // The two irrational multipliers (1.7, 2.3) spread dots across the
        // sine cycle without any visible grid pattern.
        final phaseOffset = speed > 0
            ? math.sin(col * 1.7 + row * 2.3) * _config.dotPhaseVariance
            : 0.0;

        final pulse = speed > 0
            ? math.sin(_time * speed + phaseOffset) * amplitude
            : 0.0;
        final effectiveGlowR = baseR * (1.0 + pulse).clamp(0.5, 2.0);
        final effectiveIntensity =
            (_config.glowIntensity * (1.0 + pulse)).clamp(0.0, 1.0);

        final textCol = col - _textStartCol;
        final textRow = row - _textStartRow;
        final isLit = _visible &&
            textRow >= 0 &&
            textRow < _textGrid.length &&
            textCol >= 0 &&
            textCol < (_textGrid.isNotEmpty ? _textGrid[0].length : 0) &&
            _textGrid[textRow][textCol];

        if (isLit) {
          _drawGlowDot(
            canvas,
            cx,
            cy,
            effectiveGlowR,
            effectiveIntensity,
          );
        } else {
          canvas.drawOval(
            Rect.fromCenter(
              center: Offset(cx, cy),
              width: _config.dotWidth,
              height: _config.dotHeight,
            ),
            _offPaint,
          );
        }
      }
    }
  }

  void _drawGlowDot(
    Canvas canvas,
    double cx,
    double cy,
    double glowR,
    double intensity,
  ) {
    // Glow halo: radial gradient fading from dotOnColor (at intensity) to
    // transparent at glowR.
    final glowShader = ui.Gradient.radial(
      Offset(cx, cy),
      glowR,
      [
        _config.dotOnColor.withValues(alpha: intensity),
        _config.dotOnColor.withValues(alpha: 0.0),
      ],
    );
    canvas.drawOval(
      Rect.fromCenter(
          center: Offset(cx, cy), width: glowR * 2, height: glowR * 2),
      Paint()..shader = glowShader,
    );

    // Bright solid core dot.
    canvas.drawOval(
      Rect.fromCenter(
        center: Offset(cx, cy),
        width: _config.dotWidth,
        height: _config.dotHeight,
      ),
      Paint()
        ..color = _config.dotOnColor
        ..style = PaintingStyle.fill,
    );

    // Sub-pixel internal grid: overdraw thin background-coloured lines inside
    // the dot to give it a physical LED/VFD micro-structure look.
    _drawInternalGrid(canvas, cx, cy);
  }

  /// Draws background-coloured divider lines every [internalGridSpacing]
  /// logical pixels inside the dot's bounding box in both axes.
  ///
  /// Because these lines are drawn on top of the solid core (but NOT on top of
  /// the glow halo), the glow remains smooth while the dot surface appears
  /// textured — matching how a real LED pixel glows through its physical grid.
  void _drawInternalGrid(Canvas canvas, double cx, double cy) {
    final spacing = _config.internalGridSpacing;
    if (spacing < 2) return;

    final left = cx - _config.dotWidth / 2;
    final top = cy - _config.dotHeight / 2;

    // Vertical dividers — one 1 px-wide strip every [spacing] pixels.
    for (var x = left + spacing - 1;
        x < left + _config.dotWidth;
        x += spacing) {
      canvas.drawRect(
        Rect.fromLTWH(x, top, 1.0, _config.dotHeight),
        _gapPaint,
      );
    }

    // Horizontal dividers — one 1 px-tall strip every [spacing] pixels.
    for (var y = top + spacing - 1;
        y < top + _config.dotHeight;
        y += spacing) {
      canvas.drawRect(
        Rect.fromLTWH(left, y, _config.dotWidth, 1.0),
        _gapPaint,
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  void _rebuildPaints() {
    _offPaint = Paint()
      ..color = _config.dotOffColor
      ..style = PaintingStyle.fill;
    _gapPaint = Paint()
      ..color = _config.backgroundColor
      ..style = PaintingStyle.fill;
  }

  void _rebuildLayout() {
    _rebuildTextGrid();
    _rebuildCanvasGrid();
  }

  void _rebuildTextGrid() {
    final glyphs = BitmapFont.glyphsFor(_text);
    final colCount = glyphs.isEmpty
        ? 0
        : glyphs.length * BitmapFont.cols + (glyphs.length - 1);

    _textGrid = List.generate(BitmapFont.rows, (row) {
      return List.generate(colCount, (col) {
        final charIndex = col ~/ (BitmapFont.cols + 1);
        final colInChar = col % (BitmapFont.cols + 1);
        if (charIndex >= glyphs.length || colInChar >= BitmapFont.cols) {
          return false;
        }
        final rowMask = glyphs[charIndex][row];
        return (rowMask >> (BitmapFont.cols - 1 - colInChar)) & 1 == 1;
      });
    });
  }

  void _rebuildCanvasGrid() {
    if (size.isZero()) return;

    final stride = _config.dotStride;

    // How many dot columns/rows fit in the full widget size.
    _canvasCols = (size.x / stride).floor();
    _canvasRows = (size.y / stride).floor();

    // Pixel offset so the dot grid is centred inside the widget.
    _gridOriginX = (size.x - _canvasCols * stride) / 2.0;
    _gridOriginY = (size.y - _canvasRows * stride) / 2.0;

    // Where to start drawing the text so it is centred in the canvas grid.
    final textCols = _textGrid.isNotEmpty ? _textGrid[0].length : 0;
    _textStartCol = ((_canvasCols - textCols) / 2).round();
    _textStartRow = ((_canvasRows - BitmapFont.rows) / 2).round();
  }
}
