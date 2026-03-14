import 'dart:async';

import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/constants/app_constants.dart';
import '../../core/utils/logger.dart';
import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../domain/models/message/message.dart';
import '../../domain/models/message/message_content.dart';
import '../../domain/models/message/message_status.dart';
import '../../domain/repositories/message_repository.dart';
import '../local/database/app_database.dart';
import '../local/database/daos/channels_dao.dart';
import '../local/database/daos/messages_dao.dart';

part 'message_repository_impl.g.dart';

final _log = Logger.get('MessageRepository');

class MessageRepositoryImpl implements MessageRepository {
  MessageRepositoryImpl({
    required MessagesDao messagesDao,
    required ChannelsDao channelsDao,
    required Stream<GatewayInboundFrame> frameStream,
    required String? Function() myDeviceIdGetter,
  })  : _messagesDao = messagesDao,
        _channelsDao = channelsDao,
        _myDeviceIdGetter = myDeviceIdGetter {
    _sub = frameStream.listen(_onInboundFrame);
  }

  final MessagesDao _messagesDao;
  final ChannelsDao _channelsDao;
  final String? Function() _myDeviceIdGetter;
  StreamSubscription<GatewayInboundFrame>? _sub;

  @override
  Stream<List<Message>> watchMessages(String channelId) {
    return _messagesDao
        .watchChannelMessages(channelId)
        .map((rows) => rows.map(_rowToMessage).toList());
  }

  @override
  Future<void> insertOutbound({
    required String id,
    required String channelId,
    required String senderId,
    required String contentType,
    required String body,
    required DateTime timestamp,
  }) async {
    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: contentType,
        body: body,
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.sending.name,
        isOutbound: Value(true),
      ),
    );
  }

  @override
  Future<void> updateMessageStatus(
    String messageId,
    MessageStatus status,
  ) async {
    await _messagesDao.updateStatus(messageId, status.name);
  }

  @override
  void dispose() => _sub?.cancel();

  Future<void> _onInboundFrame(GatewayInboundFrame frame) async {
    final payload = frame.payload;

    final id = payload['id']?.toString();
    final contentType = payload['content_type']?.toString();
    final body = payload['body']?.toString();
    final senderId =
        payload['sender_id']?.toString() ?? frame.senderDeviceId;
    // Ignore frames that don't carry a chat message payload (e.g. system frames).
    if (id == null || contentType == null || body == null || body.isEmpty) {
      return;
    }

    // channel_id is a client-side concept stored in metadata by the sender.
    // If absent (e.g. messages from hirocli agent), route to the default channel.
    final metadata = payload['metadata'];
    final channelId = (metadata is Map ? metadata['channel_id']?.toString() : null)
        ?? AppConstants.defaultChannelId;

    // Use the local receive time for ordering, NOT the sender's timestamp.
    // Sender clocks can drift or be misconfigured — we have no control over them.
    // Ordering by receive time guarantees messages always appear in the order
    // this device received them, regardless of what clock the sender runs.
    // The sender's original timestamp (payload['timestamp']) is available in the
    // payload for display purposes if ever needed, but is not used for DB ordering.
    final timestamp = DateTime.now().toUtc();

    final myDeviceId = _myDeviceIdGetter();
    // A message is outbound if we sent it from this device.
    final isOutbound =
        myDeviceId != null && senderId == myDeviceId;

    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: contentType,
        body: body,
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
      ),
    );

    // Touch channel lastMessageAt for list ordering.
    final existingChannel = await _channelsDao.getById(channelId);
    if (existingChannel != null) {
      await _channelsDao.insertOrUpdate(
        existingChannel.toCompanion(true).copyWith(
              lastMessageAt:
                  Value(timestamp.millisecondsSinceEpoch),
            ),
      );
    } else {
      _log.warning('Received message for unknown channel: $channelId');
    }
  }

  Message _rowToMessage(MessageRecord row) {
    final MessageContent content = switch (row.contentType) {
      'text' => TextContent(row.body),
      final other => UnsupportedContent(other),
    };
    return Message(
      id: row.id,
      channelId: row.channelId,
      senderId: row.senderId,
      content: content,
      timestamp:
          DateTime.fromMillisecondsSinceEpoch(row.timestampMs, isUtc: true),
      status: MessageStatus.fromName(row.status),
      isOutbound: row.isOutbound,
    );
  }
}

@Riverpod(keepAlive: true)
MessageRepository messageRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  final gatewayNotifier =
      ref.read(gatewayProvider.notifier);

  // Capture device ID lazily so we always check the current identity.
  String? myDeviceId() {
    final auth = ref.read(authProvider).value;
    return auth is AuthAuthenticated ? auth.identity.deviceId : null;
  }

  final repo = MessageRepositoryImpl(
    messagesDao: db.messagesDao,
    channelsDao: db.channelsDao,
    frameStream: gatewayNotifier.frameStream,
    myDeviceIdGetter: myDeviceId,
  );

  ref.onDispose(repo.dispose);
  return repo;
}
