import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

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
import '../../platform/storage/audio_storage_service.dart';
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
    required AudioStorageService audioStorage,
  })  : _messagesDao = messagesDao,
        _channelsDao = channelsDao,
        _myDeviceIdGetter = myDeviceIdGetter,
        _audioStorage = audioStorage {
    _sub = frameStream.listen(_onInboundFrame);
  }

  final MessagesDao _messagesDao;
  final ChannelsDao _channelsDao;
  final String? Function() _myDeviceIdGetter;
  final AudioStorageService _audioStorage;
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
    String? metadata,
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
        metadata: Value(metadata),
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
    final version = frame.payload['version']?.toString();
    if (version != '0.1') {
      _log.warning(
        'Dropping frame — unsupported UnifiedMessage version',
        fields: {'version': version, 'expected': '0.1'},
      );
      return;
    }

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

    // Handle event frames (delivery acks, transcription results).
    if (msg.messageType == 'event' && msg.event != null) {
      await _handleEvent(msg);
      return;
    }

    if (msg.messageType != 'message') {
      _log.debug(
        'Ignoring non-message frame',
        fields: {'message_type': msg.messageType, 'id': msg.routing.id},
      );
      return;
    }

    // Route to the appropriate content handler.
    final audioItem =
        msg.content.where((c) => c.contentType == 'audio').firstOrNull;
    final textItem =
        msg.content.where((c) => c.contentType == 'text').firstOrNull;

    if (audioItem != null) {
      await _handleInboundAudio(msg, audioItem);
    } else if (textItem != null && textItem.body.isNotEmpty) {
      await _handleInboundText(msg, textItem);
    } else {
      _log.warning(
        'Dropping frame — no usable content item',
        fields: {
          'message_id': msg.routing.id,
          'content_types': msg.content.map((c) => c.contentType).toList(),
        },
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Event handling
  // ---------------------------------------------------------------------------

  Future<void> _handleEvent(UnifiedMessage msg) async {
    final event = msg.event!;
    final refId = event.refId;
    if (refId == null || refId.isEmpty) return;

    switch (event.type) {
      case 'message.received':
        // Server acknowledged our message — double gray checks.
        await _messagesDao.updateStatus(refId, MessageStatus.delivered.name);
        _log.debug('Message marked delivered', fields: {'ref_id': refId});

      case 'message.transcribed':
        // Server finished transcribing — double blue checks + store transcript.
        await _messagesDao.updateStatus(refId, MessageStatus.read.name);
        final transcript = event.data['transcript'] as String?;
        if (transcript != null && transcript.isNotEmpty) {
          final row = await _messagesDao.getById(refId);
          if (row != null) {
            // Merge transcript into existing metadata JSON.
            final existing = row.metadata != null
                ? Map<String, dynamic>.from(
                    jsonDecode(row.metadata!) as Map)
                : <String, dynamic>{};
            existing['transcript'] = transcript;
            await _messagesDao.updateMetadata(refId, jsonEncode(existing));
          }
        }
        _log.debug('Message transcribed', fields: {'ref_id': refId});

      default:
        _log.debug(
          'Ignoring unknown event type',
          fields: {'event_type': event.type},
        );
    }
  }

  // ---------------------------------------------------------------------------
  // Inbound audio message
  // ---------------------------------------------------------------------------

  Future<void> _handleInboundAudio(
    UnifiedMessage msg,
    ContentItem audioItem,
  ) async {
    final id = msg.routing.id;
    final senderId = msg.routing.senderId;
    final channelId = msg.routing.metadata['channel_id']?.toString() ??
        AppConstants.defaultChannelId;
    final timestamp = DateTime.now().toUtc();
    final myDeviceId = _myDeviceIdGetter();
    final isOutbound = myDeviceId != null && senderId == myDeviceId;

    // Decode base64 audio and save locally. AudioStorageService handles
    // platform differences internally (file path on mobile, data URI on web).
    String? localPath;
    if (audioItem.body.isNotEmpty) {
      try {
        final bytes = Uint8List.fromList(base64Decode(audioItem.body));
        localPath = await _audioStorage.saveBytes(messageId: id, bytes: bytes);
      } catch (e) {
        _log.warning('Failed to save inbound audio', fields: {'error': e.toString()});
      }
    }

    final durationMs =
        (audioItem.metadata['duration_ms'] as num?)?.toInt() ?? 0;
    final mimeType =
        audioItem.metadata['mime_type'] as String? ?? 'audio/m4a';

    final metadataJson = jsonEncode({
      'duration_ms': durationMs,
      'mime_type': mimeType,
      'local_path': localPath,
    });

    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: 'audio',
        body: '',
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
        metadata: Value(metadataJson),
      ),
    );

    await _touchChannelTimestamp(channelId, timestamp);
  }

  // ---------------------------------------------------------------------------
  // Inbound text message
  // ---------------------------------------------------------------------------

  Future<void> _handleInboundText(
    UnifiedMessage msg,
    ContentItem textItem,
  ) async {
    final id = msg.routing.id;
    final senderId = msg.routing.senderId;
    final channelId = msg.routing.metadata['channel_id']?.toString() ??
        AppConstants.defaultChannelId;
    final timestamp = DateTime.now().toUtc();
    final myDeviceId = _myDeviceIdGetter();
    final isOutbound = myDeviceId != null && senderId == myDeviceId;

    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: textItem.contentType,
        body: textItem.body,
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
      ),
    );

    await _touchChannelTimestamp(channelId, timestamp);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  Future<void> _touchChannelTimestamp(
      String channelId, DateTime timestamp) async {
    final existingChannel = await _channelsDao.getById(channelId);
    if (existingChannel != null) {
      await _channelsDao.insertOrUpdate(
        existingChannel.toCompanion(true).copyWith(
              lastMessageAt: Value(timestamp.millisecondsSinceEpoch),
            ),
      );
    } else {
      _log.warning('Received message for unknown channel: $channelId');
    }
  }

  Message _rowToMessage(MessageRecord row) {
    final MessageContent content = switch (row.contentType) {
      'text' => TextContent(row.body),
      'audio' => _parseAudioContent(row),
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

  AudioContent _parseAudioContent(MessageRecord row) {
    if (row.metadata == null || row.metadata!.isEmpty) {
      return const AudioContent(durationMs: 0);
    }
    try {
      final meta = jsonDecode(row.metadata!) as Map<String, dynamic>;
      return AudioContent(
        durationMs: (meta['duration_ms'] as num?)?.toInt() ?? 0,
        localPath: meta['local_path'] as String?,
        transcript: meta['transcript'] as String?,
        mimeType: meta['mime_type'] as String? ?? 'audio/m4a',
      );
    } catch (_) {
      return const AudioContent(durationMs: 0);
    }
  }
}

@Riverpod(keepAlive: true)
MessageRepository messageRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  final gatewayNotifier = ref.read(gatewayProvider.notifier);
  final audioStorage = ref.read(audioStorageProvider);

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
    audioStorage: audioStorage,
  );

  ref.onDispose(repo.dispose);
  return repo;
}
