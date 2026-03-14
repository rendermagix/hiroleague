import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:uuid/uuid.dart';

import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../core/constants/app_constants.dart';
import '../../core/errors/app_exception.dart';
import '../../core/utils/logger.dart';
import '../../data/repositories/message_repository_impl.dart';
import '../../domain/models/message/message_status.dart';

part 'message_send_notifier.g.dart';

// keepAlive: action service with no reactive state — must not be auto-disposed
// mid-send since sendText() crosses async gaps and uses ref after awaits.
@Riverpod(keepAlive: true)
class MessageSendNotifier extends _$MessageSendNotifier {
  static const _uuid = Uuid();
  static final _log = Logger.get('MessageSendNotifier');

  @override
  void build() {}

  /// Sends a text message to [channelId].
  ///
  /// Writes optimistically to the DB with [MessageStatus.sending], broadcasts
  /// via the gateway, then updates the status to [MessageStatus.sent].
  /// Throws [AppException] on failure so the caller (UI) can surface the error.
  Future<void> sendText({
    required String channelId,
    required String text,
  }) async {
    final authState = ref.read(authProvider).value;
    if (authState is! AuthAuthenticated) return;

    final identity = authState.identity;
    final messageId = _uuid.v4();
    final now = DateTime.now().toUtc();

    // Capture all refs before the first await — ref must not be read after an
    // async gap in case the provider is rebuilt between awaits (Riverpod v3).
    final repo = ref.read(messageRepositoryProvider);
    final gateway = ref.read(gatewayProvider.notifier);

    try {
      await repo.insertOutbound(
        id: messageId,
        channelId: channelId,
        senderId: identity.deviceId,
        contentType: 'text',
        body: text,
        timestamp: now,
      );

      // Payload must match hirocli's UnifiedMessage schema — 'channel' and 'direction'
      // are required fields. 'channel_id' is a client-side routing concept stored
      // in metadata so that other Flutter devices can route to the right conversation.
      gateway.send({
        'id': messageId,
        'channel': AppConstants.gatewayChannelName, // required by hirocli
        'direction': 'outbound',                    // required by hirocli
        'content_type': 'text',
        'body': text,
        'sender_id': identity.deviceId,
        'recipient_id': null,
        'metadata': {'channel_id': channelId},
        'timestamp': now.toIso8601String(),
      });

      // Optimistic — we don't wait for a server delivery receipt.
      await repo.updateMessageStatus(messageId, MessageStatus.sent);
    } on AppException {
      _log.error('Failed to send message — DB or storage error');
      rethrow;
    } catch (e) {
      _log.error('Failed to send message (unexpected)', error: e);
      throw UnknownException(e.toString());
    }
  }
}
