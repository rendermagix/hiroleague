import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';

import '../../../../core/constants/app_strings.dart';
import '../../../../core/ui/theme/app_text_styles.dart';
import '../../../../core/utils/message_formatters.dart';
import '../../../../domain/models/message/message.dart';
import '../../../../domain/models/message/message_content.dart';
import '../../../../domain/models/message/message_status.dart';
import 'delivery_indicator.dart';

class AudioBubble extends StatefulWidget {
  const AudioBubble({
    super.key,
    required this.message,
    required this.content,
  });

  final Message message;
  final AudioContent content;

  @override
  State<AudioBubble> createState() => _AudioBubbleState();
}

class _AudioBubbleState extends State<AudioBubble> {
  late final AudioPlayer _player;
  bool _isPlaying = false;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  double _speed = 1.0;
  bool _transcriptExpanded = false;

  static const _speeds = [1.0, 1.5, 2.0];

  @override
  void initState() {
    super.initState();
    _player = AudioPlayer();
    _initPlayer();
  }

  Future<void> _initPlayer() async {
    final path = widget.content.localPath;
    if (path == null || path.isEmpty) return;

    try {
      if (path.startsWith('http') ||
          path.startsWith('blob:') ||
          path.startsWith('data:')) {
        await _player.setUrl(path);
      } else {
        await _player.setFilePath(path);
      }
      final dur = _player.duration;
      if (dur != null) setState(() => _duration = dur);
    } catch (_) {
      // Audio source not yet available — player stays idle.
    }

    _player.durationStream.listen((d) {
      if (d != null && mounted) setState(() => _duration = d);
    });
    _player.positionStream.listen((p) {
      if (mounted) setState(() => _position = p);
    });
    _player.playerStateStream.listen((state) {
      if (!mounted) return;
      setState(() => _isPlaying = state.playing);
      if (state.processingState == ProcessingState.completed) {
        _player.seek(Duration.zero);
        setState(() {
          _isPlaying = false;
          _position = Duration.zero;
        });
      }
    });
  }

  @override
  void didUpdateWidget(AudioBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.content.localPath != widget.content.localPath &&
        widget.content.localPath != null) {
      _initPlayer();
    }
  }

  Future<void> _togglePlay() async {
    if (_isPlaying) {
      await _player.pause();
    } else {
      await _player.play();
    }
  }

  void _cycleSpeed() {
    final idx = _speeds.indexOf(_speed);
    final next = _speeds[(idx + 1) % _speeds.length];
    setState(() => _speed = next);
    _player.setSpeed(next);
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final isOut = widget.message.isOutbound;

    final bubbleColor = isOut ? cs.primary : cs.surfaceContainerHigh;
    final contentColor = isOut ? cs.onPrimary : cs.onSurface;
    final metaColor =
        isOut ? cs.onPrimary.withValues(alpha: 0.7) : cs.onSurfaceVariant;
    final sliderActiveColor = isOut ? cs.onPrimary : cs.primary;
    final sliderInactiveColor =
        isOut ? cs.onPrimary.withValues(alpha: 0.3) : cs.outlineVariant;

    final remaining =
        _duration > _position ? _duration - _position : Duration.zero;
    final durationLabel = _isPlaying
        ? MessageFormatters.formatDuration(remaining)
        : MessageFormatters.formatDuration(_duration > Duration.zero
            ? _duration
            : Duration(milliseconds: widget.content.durationMs));

    return Align(
      alignment: isOut ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.75,
          minWidth: 200,
        ),
        child: Container(
          margin: EdgeInsets.only(
            left: isOut ? 56 : 8,
            right: isOut ? 8 : 56,
            top: 2,
            bottom: 2,
          ),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: bubbleColor,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(18),
              topRight: const Radius.circular(18),
              bottomLeft: Radius.circular(isOut ? 18 : 4),
              bottomRight: Radius.circular(isOut ? 4 : 18),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (!isOut) ...[
                Text(
                  MessageFormatters.shortDeviceId(widget.message.senderId),
                  style: AppTextStyles.messageTimestamp.copyWith(
                    color: cs.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
              ],
              _PlayerRow(
                isPlaying: _isPlaying,
                hasSource: widget.content.localPath != null,
                contentColor: contentColor,
                sliderActiveColor: sliderActiveColor,
                sliderInactiveColor: sliderInactiveColor,
                position: _position,
                duration: _duration,
                onTogglePlay: _togglePlay,
                onSeek: (v) =>
                    _player.seek(Duration(milliseconds: v.toInt())),
              ),
              _MetaRow(
                durationLabel: durationLabel,
                speed: _speed,
                metaColor: metaColor,
                contentColor: contentColor,
                timestamp: widget.message.timestamp,
                isOutbound: isOut,
                status: widget.message.status,
                onCycleSpeed: _cycleSpeed,
              ),
              if (widget.content.transcript != null &&
                  widget.content.transcript!.isNotEmpty)
                _ExpandableTranscript(
                  transcript: widget.content.transcript!,
                  isExpanded: _transcriptExpanded,
                  metaColor: metaColor,
                  contentColor: contentColor,
                  onToggle: () => setState(
                      () => _transcriptExpanded = !_transcriptExpanded),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _PlayerRow extends StatelessWidget {
  const _PlayerRow({
    required this.isPlaying,
    required this.hasSource,
    required this.contentColor,
    required this.sliderActiveColor,
    required this.sliderInactiveColor,
    required this.position,
    required this.duration,
    required this.onTogglePlay,
    required this.onSeek,
  });

  final bool isPlaying;
  final bool hasSource;
  final Color contentColor;
  final Color sliderActiveColor;
  final Color sliderInactiveColor;
  final Duration position;
  final Duration duration;
  final VoidCallback onTogglePlay;
  final ValueChanged<double> onSeek;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 36,
          height: 36,
          child: IconButton(
            padding: EdgeInsets.zero,
            icon: Icon(
              isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
              color: contentColor,
              size: 26,
            ),
            onPressed: hasSource ? onTogglePlay : null,
          ),
        ),
        const SizedBox(width: 4),
        Expanded(
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: 3,
              thumbShape:
                  const RoundSliderThumbShape(enabledThumbRadius: 5),
              overlayShape:
                  const RoundSliderOverlayShape(overlayRadius: 12),
              activeTrackColor: sliderActiveColor,
              inactiveTrackColor: sliderInactiveColor,
              thumbColor: sliderActiveColor,
              overlayColor: sliderActiveColor.withValues(alpha: 0.2),
            ),
            child: Slider(
              min: 0,
              max: duration.inMilliseconds.toDouble().clamp(1, double.infinity),
              value: position.inMilliseconds
                  .toDouble()
                  .clamp(0, duration.inMilliseconds.toDouble()),
              onChanged: duration > Duration.zero ? onSeek : null,
            ),
          ),
        ),
      ],
    );
  }
}

class _MetaRow extends StatelessWidget {
  const _MetaRow({
    required this.durationLabel,
    required this.speed,
    required this.metaColor,
    required this.contentColor,
    required this.timestamp,
    required this.isOutbound,
    required this.status,
    required this.onCycleSpeed,
  });

  final String durationLabel;
  final double speed;
  final Color metaColor;
  final Color contentColor;
  final DateTime timestamp;
  final bool isOutbound;
  final MessageStatus status;
  final VoidCallback onCycleSpeed;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, right: 2),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            durationLabel,
            style: AppTextStyles.messageTimestamp.copyWith(color: metaColor),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: onCycleSpeed,
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(
                border: Border.all(
                  color: contentColor.withValues(alpha: 0.35),
                ),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                '${speed == speed.truncateToDouble() ? speed.toStringAsFixed(0) : speed}x',
                style: AppTextStyles.messageTimestamp
                    .copyWith(color: metaColor, fontSize: 10),
              ),
            ),
          ),
          const Spacer(),
          Text(
            MessageFormatters.formatTime(timestamp),
            style:
                AppTextStyles.messageTimestamp.copyWith(color: metaColor),
          ),
          if (isOutbound) ...[
            const SizedBox(width: 3),
            DeliveryIndicator(
              status: status,
              readColor: isOutbound ? Colors.white : null,
              defaultColor: isOutbound
                  ? Colors.white.withValues(alpha: 0.6)
                  : null,
            ),
          ],
        ],
      ),
    );
  }
}

class _ExpandableTranscript extends StatelessWidget {
  const _ExpandableTranscript({
    required this.transcript,
    required this.isExpanded,
    required this.metaColor,
    required this.contentColor,
    required this.onToggle,
  });

  final String transcript;
  final bool isExpanded;
  final Color metaColor;
  final Color contentColor;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(height: 4),
        GestureDetector(
          onTap: onToggle,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                isExpanded
                    ? Icons.expand_less_rounded
                    : Icons.expand_more_rounded,
                size: 16,
                color: metaColor,
              ),
              const SizedBox(width: 2),
              Text(
                AppStrings.transcriptLabel,
                style: AppTextStyles.messageTimestamp.copyWith(
                  color: metaColor,
                  decoration: TextDecoration.underline,
                ),
              ),
            ],
          ),
        ),
        AnimatedCrossFade(
          duration: const Duration(milliseconds: 180),
          crossFadeState: isExpanded
              ? CrossFadeState.showFirst
              : CrossFadeState.showSecond,
          firstChild: Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              transcript,
              style: AppTextStyles.messageBody
                  .copyWith(color: contentColor.withValues(alpha: 0.85)),
            ),
          ),
          secondChild: const SizedBox.shrink(),
        ),
      ],
    );
  }
}
