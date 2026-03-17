import 'package:flame/game.dart';
import 'package:flutter/material.dart';

import '../experiments/dot_matrix/dot_matrix_game.dart';
import 'chat_app_bar.dart';
import 'widgets/input_bar/message_input_bar.dart';
import 'widgets/message_list.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.channelId});

  final String channelId;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  // Created in State (not static) so hot restart always picks up the latest
  // DotMatrixGame constructor, including any config changes made in code.
  late final DotMatrixGame _dotMatrixGame = DotMatrixGame();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: ChatAppBar(channelId: widget.channelId),
      body: Column(
        children: [
          // --- Dot matrix display: top ~1/3 of the body ---
          Expanded(
            flex: 1,
            child: ClipRect(
              child: GameWidget(game: _dotMatrixGame),
            ),
          ),
          // --- Message list: bottom ~2/3 ---
          Expanded(
            flex: 2,
            child: MessageList(channelId: widget.channelId),
          ),
          MessageInputBar(channelId: widget.channelId),
        ],
      ),
    );
  }
}
