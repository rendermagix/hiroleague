import 'package:flutter/material.dart';

import '../../../../core/constants/app_strings.dart';
import '../../../../domain/models/message/message.dart';
import '../../../../domain/models/message/message_content.dart';
import 'audio_bubble.dart';
import 'text_bubble.dart';

/// Dispatcher — selects the correct bubble widget for the message content type.
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message});

  final Message message;

  @override
  Widget build(BuildContext context) {
    return switch (message.content) {
      final TextContent c => TextBubble(message: message, content: c),
      final AudioContent c => AudioBubble(message: message, content: c),
      final UnsupportedContent c => _UnsupportedBubble(rawType: c.rawType),
    };
  }
}

class _UnsupportedBubble extends StatelessWidget {
  const _UnsupportedBubble({required this.rawType});

  final String rawType;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.errorContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          '[${AppStrings.unsupportedContent}: $rawType]',
          style: TextStyle(
            color: Theme.of(context).colorScheme.onErrorContainer,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}
