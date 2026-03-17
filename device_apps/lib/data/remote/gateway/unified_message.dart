/// Typed Dart representation of the UnifiedMessage v0.1 wire format.
///
/// These classes mirror hiro-channel-sdk's Python models and are intentionally
/// simple data-transfer objects — no freezed, no codegen. The [fromJson]
/// factories throw [FormatException] with a field-level message on any
/// structural mismatch, so schema changes surface immediately as logged errors
/// rather than silent drops.
///
/// [toJson] is the single authoritative place where outbound payloads are
/// constructed, ensuring sender and receiver stay in sync.
library;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Throws [FormatException] if [key] is absent or null in [json].
void _requireString(Map<String, dynamic> json, String key, String context) {
  if (json[key] is! String) {
    throw FormatException(
      '$context: "$key" must be a non-null string, got ${json[key]?.runtimeType}',
    );
  }
}

Map<String, dynamic> _asStringMap(dynamic value) {
  if (value == null) return const {};
  if (value is Map) return Map<String, dynamic>.from(value);
  throw FormatException('Expected a JSON object, got ${value.runtimeType}');
}

// ---------------------------------------------------------------------------
// ContentItem
// ---------------------------------------------------------------------------

/// A single piece of content within a [UnifiedMessage].
///
/// A message may carry multiple items — e.g. a text caption alongside several
/// images and a PDF. Order is preserved and meaningful.
class ContentItem {
  const ContentItem({
    required this.contentType,
    this.body = '',
    this.metadata = const {},
  });

  final String contentType;
  final String body;
  final Map<String, dynamic> metadata;

  factory ContentItem.fromJson(Map<String, dynamic> json) {
    _requireString(json, 'content_type', 'ContentItem');
    return ContentItem(
      contentType: json['content_type'] as String,
      body: json['body'] as String? ?? '',
      metadata: _asStringMap(json['metadata']),
    );
  }

  Map<String, dynamic> toJson() => {
        'content_type': contentType,
        'body': body,
        'metadata': metadata,
      };
}

// ---------------------------------------------------------------------------
// MessageRouting
// ---------------------------------------------------------------------------

/// Routing and identification envelope within a [UnifiedMessage].
///
/// Carries who sent the message, which channel it belongs to, where it should
/// go, and when it was created. [direction] is always from hirocli's
/// perspective: "inbound" (from a third party) or "outbound" (to a third party).
class MessageRouting {
  const MessageRouting({
    required this.id,
    required this.channel,
    required this.direction,
    required this.senderId,
    this.recipientId,
    this.timestamp,
    this.metadata = const {},
  });

  final String id;
  final String channel;
  final String direction;
  final String senderId;
  final String? recipientId;

  /// ISO-8601 string. Nullable — the server overrides inbound timestamps with
  /// its own receive time, so the device value is informational only.
  final String? timestamp;
  final Map<String, dynamic> metadata;

  factory MessageRouting.fromJson(Map<String, dynamic> json) {
    const ctx = 'MessageRouting';
    _requireString(json, 'id', ctx);
    _requireString(json, 'channel', ctx);
    _requireString(json, 'direction', ctx);
    _requireString(json, 'sender_id', ctx);
    return MessageRouting(
      id: json['id'] as String,
      channel: json['channel'] as String,
      direction: json['direction'] as String,
      senderId: json['sender_id'] as String,
      recipientId: json['recipient_id'] as String?,
      timestamp: json['timestamp'] as String?,
      metadata: _asStringMap(json['metadata']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'channel': channel,
        'direction': direction,
        'sender_id': senderId,
        if (recipientId != null) 'recipient_id': recipientId,
        if (timestamp != null) 'timestamp': timestamp,
        'metadata': metadata,
      };
}

// ---------------------------------------------------------------------------
// UnifiedMessage
// ---------------------------------------------------------------------------

/// Canonical cross-channel message format v0.1.
///
/// Structure:
///   - [version]      — schema version for forward compatibility
///   - [messageType]  — communication intent: "message" now; "request" /
///                      "response" / "stream" reserved for future use
///   - [routing]      — who/where/when
///   - [content]      — ordered list of content items
///
/// See architecture/unified-message in mintdocs for full field reference.
class UnifiedMessage {
  const UnifiedMessage({
    this.version = '0.1',
    this.messageType = 'message',
    required this.routing,
    required this.content,
  });

  final String version;
  final String messageType;
  final MessageRouting routing;
  final List<ContentItem> content;

  /// Parses a [UnifiedMessage] from a decoded JSON map.
  ///
  /// Throws [FormatException] with a descriptive message if any required field
  /// is missing or has the wrong type. Never returns a partially-populated
  /// instance — callers should catch and log, then discard the frame.
  factory UnifiedMessage.fromJson(Map<String, dynamic> json) {
    const ctx = 'UnifiedMessage';
    _requireString(json, 'version', ctx);
    _requireString(json, 'message_type', ctx);

    final routingRaw = json['routing'];
    if (routingRaw is! Map) {
      throw FormatException(
        '$ctx: "routing" must be a JSON object, got ${routingRaw?.runtimeType}',
      );
    }
    final contentRaw = json['content'];
    if (contentRaw is! List) {
      throw FormatException(
        '$ctx: "content" must be a JSON array, got ${contentRaw?.runtimeType}',
      );
    }

    return UnifiedMessage(
      version: json['version'] as String,
      messageType: json['message_type'] as String,
      routing: MessageRouting.fromJson(Map<String, dynamic>.from(routingRaw)),
      content: contentRaw.indexed
          .map((entry) {
            final (i, item) = entry;
            if (item is! Map) {
              throw FormatException(
                '$ctx: content[$i] must be a JSON object, got ${item.runtimeType}',
              );
            }
            return ContentItem.fromJson(Map<String, dynamic>.from(item));
          })
          .toList(),
    );
  }

  Map<String, dynamic> toJson() => {
        'version': version,
        'message_type': messageType,
        'routing': routing.toJson(),
        'content': content.map((c) => c.toJson()).toList(),
      };
}
