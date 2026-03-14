abstract final class AppConstants {
  static const String appName = 'Hiro';
  static const String appVersion = '0.1.0';

  // Layout
  static const double wideLayoutBreakpoint = 720.0;

  // Gateway / WebSocket
  static const Duration authTimeout = Duration(seconds: 20);
  static const Duration pairingTimeout = Duration(seconds: 40);
  static const Duration reconnectInitialDelay = Duration(seconds: 2);
  static const Duration reconnectMaxDelay = Duration(seconds: 30);
  static const Duration heartbeatInterval = Duration(seconds: 30);

  // Messaging — wire format (must match hirocli UnifiedMessage schema)
  /// Transport channel name registered on hirocli.
  static const String gatewayChannelName = 'devices';

  // Local channel IDs (client-side only, not known to the server)
  /// The default "General" channel seeded on first launch.
  static const String defaultChannelId = 'default-general-v1';
  static const String defaultChannelName = 'General';
}
