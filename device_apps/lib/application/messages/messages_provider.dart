import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../data/repositories/message_repository_impl.dart';
import '../../domain/models/message/message.dart';

part 'messages_provider.g.dart';

/// Live stream of messages for [channelId], sorted oldest→newest.
///
/// Riverpod v3 marks `Ref` as deprecated in function-based providers to nudge
/// toward class-based providers. The function form is still supported and
/// correct for simple stream providers like this one.
@riverpod
// ignore: deprecated_member_use_from_same_package
Stream<List<Message>> channelMessages(
  Ref ref,
  String channelId,
) {
  // Ensure the ingest subscription is alive whenever a chat screen is open.
  ref.watch(messageRepositoryProvider);
  return ref
      .read(messageRepositoryProvider)
      .watchMessages(channelId);
}
