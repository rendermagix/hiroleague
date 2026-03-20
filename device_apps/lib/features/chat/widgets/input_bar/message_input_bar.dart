import 'dart:async' show unawaited;

import 'package:flutter/gestures.dart' show LongPressGestureRecognizer;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../application/providers.dart';
import '../../../../core/constants/app_strings.dart';
import '../../../../core/errors/app_exception.dart';
import 'mic_permission_dialog.dart';

class MessageInputBar extends ConsumerStatefulWidget {
  const MessageInputBar({super.key, required this.channelId});

  final String channelId;

  @override
  ConsumerState<MessageInputBar> createState() => _MessageInputBarState();
}

class _MessageInputBarState extends ConsumerState<MessageInputBar>
    with SingleTickerProviderStateMixin {
  final _controller = TextEditingController();
  bool _hasText = false;

  // Purely UI: pulse animation drives both the mic scale and the recording dot.
  late final AnimationController _pulseCtrl;
  late final Animation<double> _pulseAnim;

  // How far the mic + slide hint have been dragged left (0 = no drag).
  // Clamped to [_cancelThreshold, 0]; reset to 0 on release or cancel.
  double _dragOffset = 0.0;

  // Cancel when finger drifts 1/3 of the screen width to the left.
  double _cancelThreshold(BuildContext ctx) =>
      -(MediaQuery.sizeOf(ctx).width / 3);

  @override
  void initState() {
    super.initState();
    _controller.addListener(_onTextChanged);
    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _pulseAnim = Tween<double>(begin: 1.0, end: 1.35).animate(
      CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut),
    );
  }

  // ---------------------------------------------------------------------------
  // Text send
  // ---------------------------------------------------------------------------

  void _onTextChanged() {
    final has = _controller.text.trim().isNotEmpty;
    if (has != _hasText) setState(() => _hasText = has);
  }

  Future<void> _sendText() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    _controller.clear();
    final sender = ref.read(messageSendProvider.notifier);
    try {
      await sender.sendText(channelId: widget.channelId, text: text);
    } on AppException catch (e) {
      if (mounted) _showError('${AppStrings.messageSendFailed}: ${e.message}');
    } catch (_) {
      if (mounted) _showError(AppStrings.messageSendFailed);
    }
  }

  // ---------------------------------------------------------------------------
  // Recording gestures — delegate logic to RecordingNotifier
  // ---------------------------------------------------------------------------

  void _onLongPressStart(LongPressStartDetails details) {
    final recording = ref.read(recordingProvider);
    if (recording is! RecordingIdle) return;
    if (!recording.hasMicrophone) {
      _showError(AppStrings.noMicrophoneDetected);
      return;
    }
    if (!recording.micPermissionGranted) {
      unawaited(_showPermissionFlow(recording.previouslyDenied));
      return;
    }
    setState(() => _dragOffset = 0.0);
    unawaited(_startRecording());
  }

  Future<void> _showPermissionFlow(bool previouslyDenied) async {
    if (!mounted) return;
    final action = await showMicPermissionDialog(
      context,
      previouslyDenied: previouslyDenied,
    );
    if (!mounted) return;
    final notifier = ref.read(recordingProvider.notifier);
    switch (action) {
      case MicPermissionDialogResult.requestPermission:
        final status = await notifier.ensurePermission();
        if (status == MicPermissionStatus.denied && mounted) {
          _showError(AppStrings.micPermissionDenied);
        }
      case MicPermissionDialogResult.openSettings:
        await notifier.openPermissionSettings();
      case MicPermissionDialogResult.dismissed:
        break;
    }
  }

  Future<void> _startRecording() async {
    try {
      await ref.read(recordingProvider.notifier).startRecording();
    } catch (_) {
      if (mounted) _showError(AppStrings.recordingStartError);
    }
  }

  void _onLongPressMoveUpdate(LongPressMoveUpdateDetails details) {
    if (ref.read(recordingProvider) is! RecordingActive) return;
    final dx = details.offsetFromOrigin.dx;
    final threshold = _cancelThreshold(context);
    if (dx < threshold) {
      // Snap back before cancelling so the button doesn't freeze off-screen.
      setState(() => _dragOffset = 0.0);
      unawaited(ref.read(recordingProvider.notifier).cancelRecording());
      return;
    }
    // Clamp to [threshold, 0] — no rightward drift beyond origin.
    setState(() => _dragOffset = dx.clamp(threshold, 0.0));
  }

  void _onLongPressEnd(LongPressEndDetails _) {
    setState(() => _dragOffset = 0.0);
    unawaited(_stopAndSend());
  }

  Future<void> _stopAndSend() async {
    final recorder = ref.read(recordingProvider.notifier);
    final sender = ref.read(messageSendProvider.notifier);
    final result = await recorder.stopRecording();
    if (result == null || result.durationMs < 200) return;
    if (!mounted) return;
    await _sendAudio(sender, result);
  }

  Future<void> _sendAudio(
    MessageSendNotifier sender,
    AudioRecordingResult result,
  ) async {
    try {
      await sender.sendAudio(
        channelId: widget.channelId,
        recordingResult: result,
      );
    } on AppException catch (e) {
      if (mounted) _showError('${AppStrings.audioSendFailed}: ${e.message}');
    } catch (_) {
      if (mounted) _showError(AppStrings.audioSendFailed);
    }
  }

  // ---------------------------------------------------------------------------
  // RecordingState listener — drives pulse animation and handles auto-complete
  // ---------------------------------------------------------------------------

  void _onRecordingStateChange(RecordingState? prev, RecordingState next) {
    if (next is RecordingCompleted) {
      ref.read(recordingProvider.notifier).acknowledgeCompleted();
      final result = next.result;
      if (result != null && result.durationMs >= 200) {
        final sender = ref.read(messageSendProvider.notifier);
        unawaited(_sendAudio(sender, result));
      }
      return;
    }
    if (next is RecordingActive && prev is! RecordingActive) {
      _pulseCtrl.repeat(reverse: true);
    } else if (next is! RecordingActive && prev is RecordingActive) {
      _pulseCtrl
        ..stop()
        ..reset();
      // Guard: ensure offset is reset if recording ends without a gesture end
      // (e.g. auto-stopped at 60 s).
      if (mounted) setState(() => _dragOffset = 0.0);
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating),
    );
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------

  // The mic GestureDetector must remain at the same tree position (last child
  // of the Row) across idle↔recording transitions so Flutter keeps the active
  // gesture recognizer alive and preserves drag tracking.
  @override
  Widget build(BuildContext context) {
    ref.listen<RecordingState>(recordingProvider, _onRecordingStateChange);

    final cs = Theme.of(context).colorScheme;
    final isConnected = ref.watch(gatewayProvider) is GatewayConnected;
    final recordingState = ref.watch(recordingProvider);
    final RecordingActive? activeState =
        recordingState is RecordingActive ? recordingState : null;
    final isRecording = activeState != null;

    final threshold = _cancelThreshold(context);
    // progress ∈ [0, 1]: 0 = no drag, 1 = at cancel threshold.
    final dragProgress =
        threshold != 0 ? (_dragOffset / threshold).clamp(0.0, 1.0) : 0.0;

    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
        decoration: BoxDecoration(
          color: cs.surface,
          border: Border(
            top: BorderSide(color: cs.outlineVariant, width: 0.5),
          ),
        ),
        // clipBehavior: none lets the enlarged mic overflow the bar edges.
        clipBehavior: Clip.none,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Left side: timer when recording, text field when idle.
            Expanded(
              child: activeState != null
                  ? _RecordingTimer(
                      elapsedSeconds: activeState.elapsedSeconds,
                      pulseAnimation: _pulseAnim,
                    )
                  : TextField(
                      controller: _controller,
                      enabled: isConnected,
                      maxLines: 5,
                      minLines: 1,
                      textInputAction: TextInputAction.newline,
                      keyboardType: TextInputType.multiline,
                      decoration: InputDecoration(
                        hintText: isConnected
                            ? AppStrings.chatInputHint
                            : AppStrings.chatConnecting,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24),
                          borderSide: BorderSide.none,
                        ),
                        filled: true,
                        fillColor: cs.surfaceContainerHigh,
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 10),
                        isDense: true,
                      ),
                    ),
            ),
            const SizedBox(width: 8),
            // Send button or mic button. Both resolve to the same tree slot —
            // Flutter updates in-place, keeping the gesture recognizer alive.
            if (_hasText && !isRecording)
              AnimatedOpacity(
                opacity: isConnected ? 1.0 : 0.5,
                duration: const Duration(milliseconds: 150),
                child: IconButton.filled(
                  onPressed: (isConnected && _hasText) ? _sendText : null,
                  icon: const Icon(Icons.send_rounded),
                  style: IconButton.styleFrom(
                    backgroundColor: cs.primary,
                    foregroundColor: cs.onPrimary,
                  ),
                ),
              )
            else
              // RawGestureDetector with a short 150ms hold duration instead of
              // Flutter's default ~500ms — makes recording feel instant.
              RawGestureDetector(
                gestures: {
                  LongPressGestureRecognizer:
                      GestureRecognizerFactoryWithHandlers<
                          LongPressGestureRecognizer>(
                    () => LongPressGestureRecognizer(
                      duration: const Duration(milliseconds: 150),
                    ),
                    (instance) {
                      instance
                        ..onLongPressStart =
                            isConnected ? _onLongPressStart : null
                        ..onLongPressMoveUpdate =
                            isConnected ? _onLongPressMoveUpdate : null
                        ..onLongPressEnd =
                            isConnected ? _onLongPressEnd : null;
                    },
                  ),
                },
                child: Transform.translate(
                  offset: Offset(_dragOffset, 0),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      if (isRecording)
                        _SlideToCancelHint(dragProgress: dragProgress),
                      _MicButton(
                        isRecording: isRecording,
                        isConnected: isConnected,
                        pulseAnimation: _pulseAnim,
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _controller.removeListener(_onTextChanged);
    _controller.dispose();
    _pulseCtrl.dispose();
    super.dispose();
  }
}

// ---------------------------------------------------------------------------
// Named sub-widgets
// ---------------------------------------------------------------------------

/// Timer shown on the left while recording. Stays fixed; only the slide hint
/// and mic button translate with the drag.
class _RecordingTimer extends StatelessWidget {
  const _RecordingTimer({
    required this.elapsedSeconds,
    required this.pulseAnimation,
  });

  final int elapsedSeconds;
  final Animation<double> pulseAnimation;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final m = (elapsedSeconds ~/ 60).toString().padLeft(2, '0');
    final s = (elapsedSeconds % 60).toString().padLeft(2, '0');

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Pulsing red dot — reuses the mic pulse animation for sync.
        AnimatedBuilder(
          animation: pulseAnimation,
          builder: (_, __) => Container(
            width: 10 * pulseAnimation.value,
            height: 10 * pulseAnimation.value,
            decoration:
                BoxDecoration(color: cs.error, shape: BoxShape.circle),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '$m:$s',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontFeatures: const [FontFeature.tabularFigures()],
                color: cs.onSurface,
                fontWeight: FontWeight.w600,
              ),
        ),
      ],
    );
  }
}

/// "← slide to cancel" hint that sits immediately left of the mic button and
/// moves with it. Fades and turns red as the drag approaches the threshold.
class _SlideToCancelHint extends StatelessWidget {
  const _SlideToCancelHint({required this.dragProgress});

  /// 0 = no drag, 1 = at cancel threshold.
  final double dragProgress;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final color =
        Color.lerp(cs.onSurfaceVariant, cs.error, dragProgress)!;
    final opacity = (1.0 - dragProgress * 0.5).clamp(0.5, 1.0);

    return Opacity(
      opacity: opacity,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.chevron_left_rounded, color: color, size: 20),
          Text(
            AppStrings.slideToCancelRecording,
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: color),
          ),
          const SizedBox(width: 8),
        ],
      ),
    );
  }
}

/// Mic button — renders idle (primary colour) or recording (pulsing red, 1.5×
/// size) state. Overflow is intentional: the parent Row has Clip.none so the
/// enlarged button can bleed outside the bar's padding box.
class _MicButton extends StatelessWidget {
  const _MicButton({
    required this.isRecording,
    required this.isConnected,
    required this.pulseAnimation,
  });

  final bool isRecording;
  final bool isConnected;
  final Animation<double> pulseAnimation;

  // Idle size and 1.5× recording size.
  static const double _idleSize = 48;
  static const double _recordingSize = 72; // 48 × 1.5

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return AnimatedOpacity(
      opacity: isConnected ? 1.0 : 0.5,
      duration: const Duration(milliseconds: 150),
      child: isRecording ? _buildRecording(cs) : _buildIdle(cs),
    );
  }

  Widget _buildIdle(ColorScheme cs) {
    return Container(
      width: _idleSize,
      height: _idleSize,
      decoration: BoxDecoration(color: cs.primary, shape: BoxShape.circle),
      child: Icon(Icons.mic_rounded, color: cs.onPrimary),
    );
  }

  Widget _buildRecording(ColorScheme cs) {
    return AnimatedBuilder(
      animation: pulseAnimation,
      builder: (_, child) =>
          Transform.scale(scale: pulseAnimation.value, child: child),
      child: Container(
        width: _recordingSize,
        height: _recordingSize,
        decoration: BoxDecoration(
          color: cs.error,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: cs.error.withValues(alpha: 0.4),
              blurRadius: 14,
              spreadRadius: 4,
            ),
          ],
        ),
        child: Icon(Icons.mic_rounded, color: cs.onError, size: 32),
      ),
    );
  }
}
