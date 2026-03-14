import 'package:flutter/material.dart';

/// Hiro-specific text style overrides.
/// Material3 base typography is handled by FlexColorScheme — only
/// app-domain styles are defined here.
abstract final class AppTextStyles {
  static const TextStyle messageBody = TextStyle(
    fontSize: 15,
    fontWeight: FontWeight.w400,
    height: 1.4,
  );

  static const TextStyle messageTimestamp = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w400,
    letterSpacing: 0.4,
  );

  static const TextStyle channelTitle = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w600,
    letterSpacing: 0.1,
  );

  static const TextStyle channelSubtitle = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    letterSpacing: 0.1,
  );

  static const TextStyle unreadBadge = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w700,
  );
}
