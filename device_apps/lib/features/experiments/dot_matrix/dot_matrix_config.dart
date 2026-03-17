import 'package:flutter/painting.dart';

/// Configuration for the dot matrix display widget.
///
/// All dimensions are in logical pixels. Defaults produce a
/// green-on-black retro LED display look.
class DotMatrixConfig {
  const DotMatrixConfig({
    this.dotWidth = 15.0,
    this.dotHeight = 15.0,
    this.dotSpacing = 6.0,
    this.dotOnColor = const Color(0xFF00FF88),
    this.dotOffColor = const Color(0x18FFFFFF),
    this.backgroundColor = const Color(0xFF223136),
    this.glowRadius = 1.8,
    this.glowIntensity = 0.45,
    this.pulseSpeed = 2.5,
    this.pulseAmplitude = 0.15,
    this.dotPhaseVariance = 0.68,
    this.internalGridSpacing = 5,
    this.showDuration = 10.8,
    this.pauseDuration = 0.5,
  });

  // ---------------------------------------------------------------------------
  // Dot appearance
  // ---------------------------------------------------------------------------

  /// Width of each dot in logical pixels.
  /// Range: 2.0 – 8.0. Smaller = denser grid; larger = chunky LED look.
  final double dotWidth;

  /// Height of each dot in logical pixels.
  /// Range: 2.0 – 8.0. Set equal to [dotWidth] for circular dots, or
  /// different values for rectangular/pill dots.
  final double dotHeight;

  /// Gap between dot centres minus the dot size, in logical pixels.
  /// Range: 1.0 – 6.0. 0 = dots touching; 4+ = sparse matrix.
  final double dotSpacing;

  // ---------------------------------------------------------------------------
  // Colors
  // ---------------------------------------------------------------------------

  /// Color of a lit ("on") dot.
  /// Range: any opaque Color. Classic choices:
  ///   0xFF00FF88  – green LED (default)
  ///   0xFF00CFFF  – cyan/blue LED
  ///   0xFFFF6600  – amber LED
  ///   0xFFFF2244  – red LED
  ///   0xFFFFFFCC  – warm white LED
  final Color dotOnColor;

  /// Color of an unlit ("off") dot, shown as a faint grid behind the text.
  /// Range: any Color with low alpha (0x00 – 0x30 alpha looks best).
  /// Set fully transparent (0x00000000) to hide the off-dot grid entirely.
  final Color dotOffColor;

  /// Background fill color of the widget.
  /// Range: any Color. Near-black (0xFF090D0E – 0xFF1A1A1A) maximises glow
  /// contrast. Use 0xFF000000 for pure black.
  final Color backgroundColor;

  // ---------------------------------------------------------------------------
  // Glow
  // ---------------------------------------------------------------------------

  /// Radius of the glow halo as a multiplier of the larger of [dotWidth] /
  /// [dotHeight].
  /// Range: 1.0 – 4.0.
  ///   1.0 = tight halo just outside the dot edge
  ///   2.0 – 2.5 = soft, natural LED bloom (default ≈ 2.2)
  ///   3.0+ = wide diffuse glow, overlapping neighbours
  final double glowRadius;

  /// Opacity of the glow layer drawn behind each lit dot.
  /// Range: 0.0 – 1.0.
  ///   0.0 = no glow (sharp dots only)
  ///   0.4 – 0.6 = subtle bloom (default ≈ 0.55)
  ///   0.8+ = intense halo; can look oversaturated at high densities
  final double glowIntensity;

  /// Speed of the glow pulse in radians per second (drives a sine wave).
  /// Range: 0.0 – 4.0.
  ///   0.0 = no pulse, glow is fully static
  ///   0.5 – 1.5 = slow, breathing LED feel (default ≈ 1.2)
  ///   2.0 – 4.0 = fast flickering / urgent feel
  final double pulseSpeed;

  /// How much the glow breathes around its base values, as a fraction.
  /// Range: 0.0 – 0.5.
  ///   0.0 = no oscillation (even when pulseSpeed > 0)
  ///   0.15 – 0.3 = gentle breathing (default ≈ 0.25)
  ///   0.5 = glow radius and intensity swing ±50% each cycle
  final double pulseAmplitude;

  /// Per-dot phase offset in radians, derived from each dot's grid position.
  /// Breaks the perfectly synchronised lockstep without being distracting.
  /// Range: 0.0 – 0.8 radians.
  ///   0.0 = all dots pulse in perfect unison
  ///   0.2 – 0.35 = subtle organic variation, barely noticeable (default ≈ 0.28)
  ///   0.6+ = clearly visible individual differences across the grid
  final double dotPhaseVariance;

  /// Sub-pixel grid spacing inside each individual lit dot.
  ///
  /// Each dot's bounding box is overlaid with background-colored divider lines
  /// every N logical pixels in both axes, making the dot look like a tiny grid
  /// of sub-pixels rather than a solid blob — like the physical structure of a
  /// real LED or VFD dot.
  ///
  /// Example: dotWidth = 15, internalGridSpacing = 5 → divider lines at x=4,
  /// x=9, x=14 and y=4, y=9, y=14 inside the dot (4 on + 1 off repeating).
  ///
  /// Range: 0 (disabled) or 2 – dotWidth.
  ///   0      = no internal grid, dot is a solid filled oval
  ///   3 – 4  = very dense: chunky pixel look
  ///   5 – 6  = default: subtle sub-pixel texture (default = 5)
  ///   10+    = very sparse, barely visible
  ///
  /// Has no effect if the dot size is smaller than the spacing.
  final int internalGridSpacing;

  // ---------------------------------------------------------------------------
  // Animation timing
  // ---------------------------------------------------------------------------

  /// How long each word is displayed before fading out, in seconds.
  /// Range: 0.5 – 5.0.
  final double showDuration;

  /// Blank pause between words (after hide, before next word shows), in
  /// seconds. Range: 0.1 – 2.0.
  final double pauseDuration;

  // ---------------------------------------------------------------------------
  // Derived helpers
  // ---------------------------------------------------------------------------

  /// Total advance (centre-to-centre) per dot column/row.
  double get dotStride => (dotWidth > dotHeight ? dotWidth : dotHeight) + dotSpacing;
}
