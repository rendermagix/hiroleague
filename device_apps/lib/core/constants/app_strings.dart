/// All user-facing strings. Use these in widgets — no hardcoded strings.
/// Will be migrated to ARB files when i18n is added.
abstract final class AppStrings {
  static const String appName = 'Hiro';

  // Navigation labels
  static const String navChannels = 'Channels';
  static const String navSettings = 'Settings';

  // Placeholder text (Foundation phase)
  static const String channelsPlaceholder = 'Channels — coming in Chat phase';
  static const String settingsPlaceholder = 'Settings — coming later';
  static const String onboardingPlaceholder = 'Onboarding — coming in Identity phase';

  // Common actions
  static const String retry = 'Retry';
  static const String cancel = 'Cancel';
  static const String confirm = 'Confirm';
  static const String close = 'Close';

  // Onboarding — paste / QR
  static const String pastePairingObject = 'Paste connection info';
  static const String pasteClipboardEmpty = 'Nothing found in clipboard';
  static const String pasteInvalidJson = 'Clipboard does not contain a valid pairing object';
  static const String qrScanButton = 'Scan QR Code';
  static const String qrScanTitle = 'Scan QR Code';
  static const String qrInvalidJson = 'QR code does not contain a valid pairing object';
  static const String pairingExpiresIn = 'Expires in';
  static const String pairingExpired = 'Expired';

  // Settings — disconnect
  static const String disconnectFromGateway = 'Disconnect from gateway';
  static const String disconnectConfirmTitle = 'Disconnect?';
  static const String disconnectConfirmBody =
      'This will remove your gateway connection and return you to the connection screen.';
  static const String disconnectConfirmAction = 'Disconnect';

  // Chat — input bar
  static const String chatInputHint = 'Type a message\u2026';
  static const String chatConnecting = 'Connecting to gateway\u2026';
  static const String slideToCancelRecording = 'Slide to cancel';

  // Chat — mic permission (web)
  static const String micPermissionRequired =
      'Microphone access is required. Please allow it in your browser and try again.';
  static const String micPermissionError =
      'Could not request microphone permission.';

  // Chat — recording errors
  static const String recordingStartError = 'Could not start recording';

  // Chat — send errors
  static const String messageSendFailed = 'Failed to send message';
  static const String audioSendFailed = 'Failed to send audio';

  // Chat — audio bubble
  static const String transcriptLabel = 'Transcript';

  // Chat — unsupported content
  static const String unsupportedContent = 'Unsupported content';

  // Errors
  static const String errorGeneric = 'Something went wrong. Please try again.';
  static const String errorNetwork = 'Network error. Check your connection.';
  static const String errorAuth = 'Authentication failed.';
}
