import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../../../../core/constants/app_strings.dart';

/// Shows an in-app explanation dialog before triggering the OS/browser mic
/// permission prompt. Returns `true` if the user tapped Continue (or Open
/// Settings), `false` if dismissed.
///
/// When [previouslyDenied] is true, an "Open Settings" button is shown
/// alongside "Try Again" (mobile) or a browser-specific message (web).
Future<MicPermissionDialogResult> showMicPermissionDialog(
  BuildContext context, {
  required bool previouslyDenied,
}) async {
  final result = await showDialog<MicPermissionDialogResult>(
    context: context,
    builder: (_) => _MicPermissionDialog(previouslyDenied: previouslyDenied),
  );
  return result ?? MicPermissionDialogResult.dismissed;
}

enum MicPermissionDialogResult { requestPermission, openSettings, dismissed }

class _MicPermissionDialog extends StatelessWidget {
  const _MicPermissionDialog({required this.previouslyDenied});

  final bool previouslyDenied;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text(AppStrings.micPermissionDialogTitle),
      content: Text(
        previouslyDenied && kIsWeb
            ? AppStrings.micPermissionDeniedWeb
            : AppStrings.micPermissionDialogBody,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context)
              .pop(MicPermissionDialogResult.dismissed),
          child: const Text(AppStrings.micPermissionDialogNotNow),
        ),
        if (previouslyDenied && !kIsWeb)
          TextButton(
            onPressed: () => Navigator.of(context)
                .pop(MicPermissionDialogResult.openSettings),
            child: const Text(AppStrings.micPermissionDialogOpenSettings),
          ),
        if (!previouslyDenied || !kIsWeb)
          FilledButton(
            onPressed: () => Navigator.of(context)
                .pop(MicPermissionDialogResult.requestPermission),
            child: Text(
              previouslyDenied
                  ? AppStrings.retry
                  : AppStrings.micPermissionDialogContinue,
            ),
          ),
      ],
    );
  }
}
