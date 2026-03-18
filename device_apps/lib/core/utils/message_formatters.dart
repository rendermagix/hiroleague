/// Shared formatting utilities for message bubble widgets.
abstract final class MessageFormatters {
  /// Truncates a device ID to its last 8 characters with an ellipsis prefix.
  static String shortDeviceId(String id) {
    if (id.length <= 8) return id;
    return '\u2026${id.substring(id.length - 8)}';
  }

  /// Formats a UTC [DateTime] as local HH:mm.
  static String formatTime(DateTime dt) {
    final local = dt.toLocal();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  /// Formats a [Duration] as mm:ss.
  static String formatDuration(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }
}
