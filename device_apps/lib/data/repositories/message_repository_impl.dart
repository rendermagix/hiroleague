import 'dart:async';

import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/constants/app_constants.dart';
import '../../core/utils/logger.dart';
import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../data/remote/gateway/unified_message.dart';
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
    // --- Fix 2: version guard ---
    // Check version before any field access. Unknown versions likely have a
    // different structure and would either misparse silently or throw confusing
    // errors further down. Fail fast and visibly here instead.
    final version = frame.payload['version']?.toString();
    if (version != '0.1') {
      _log.warning(
        'Dropping frame — unsupported UnifiedMessage version',
        fields: {'version': version, 'expected': '0.1'},
      );
      return;
    }

    // --- Fix 3: typed parse with throwing fromJson ---
    // Any missing or wrong-typed required field throws a FormatException with
    // the exact field name. Caught here and logged as a WARNING so schema
    // mismatches are immediately visible in the log rather than silent drops.
    late UnifiedMessage msg;
    try {
      msg = UnifiedMessage.fromJson(frame.payload);
    } on FormatException catch (e) {
      _log.warning(
        'Dropping malformed frame — schema mismatch',
        fields: {'error': e.message},
      );
      return;
    }

    // Only process content-exchange messages. Future types (request, response,
    // stream) will be handled by their own consumers.
    if (msg.messageType != 'message') {
      _log.debug(
        'Ignoring non-message frame',
        fields: {'message_type': msg.messageType, 'id': msg.routing.id},
      );
      return;
    }

    // Find the first text content item to store and display.
    final textItem = msg.content.where((c) => c.contentType == 'text').firstOrNull;
    if (textItem == null || textItem.body.isEmpty) {
      _log.warning(
        'Dropping frame — no text content item',
        fields: {
          'message_id': msg.routing.id,
          'content_types': msg.content.map((c) => c.contentType).toList(),
        },
      );
      return;
    }

    final id = msg.routing.id;
    final senderId = msg.routing.senderId;
    final contentType = textItem.contentType;
    final body = textItem.body;

    // channel_id is stored in routing.metadata by the sender.
    // If absent (e.g. replies from the hirocli agent), route to the default channel.
    final channelId =
        msg.routing.metadata['channel_id']?.toString() ?? AppConstants.defaultChannelId;

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
