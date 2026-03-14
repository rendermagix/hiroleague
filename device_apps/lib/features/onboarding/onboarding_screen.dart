import 'dart:async';
import 'dart:convert';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../core/constants/app_strings.dart';
import '../../core/constants/route_names.dart';
import '../../core/utils/platform_utils.dart';
import '../../domain/models/pairing/pairing_object.dart';
import 'qr_scan_screen.dart';
import 'widgets/gateway_url_field.dart';
import 'widgets/pairing_code_form.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _formKey = GlobalKey<FormState>();
  final _gatewayUrlController = TextEditingController();
  final _pairingCodeController = TextEditingController();
  final _deviceNameController = TextEditingController();

  PairingObject? _parsedPairing;
  Timer? _expiryTimer;
  // Hidden if the device has no camera or user permanently denied permission.
  bool _showQrButton = PlatformUtils.isMobile;

  @override
  void initState() {
    super.initState();
    _loadDeviceName();
  }

  @override
  void dispose() {
    _gatewayUrlController.dispose();
    _pairingCodeController.dispose();
    _deviceNameController.dispose();
    _expiryTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadDeviceName() async {
    // kIsWeb has no meaningful device name; skip auto-population on web.
    if (kIsWeb) return;
    try {
      final deviceInfo = DeviceInfoPlugin();
      String name = '';
      if (defaultTargetPlatform == TargetPlatform.iOS) {
        final info = await deviceInfo.iosInfo;
        // iosInfo.name is the user-assigned device name from Settings.
        name = info.name;
      } else if (defaultTargetPlatform == TargetPlatform.android) {
        final info = await deviceInfo.androidInfo;
        name = info.model;
      }
      if (mounted && name.isNotEmpty) {
        _deviceNameController.text = name;
      }
    } catch (_) {
      // Device name is optional; silently ignore if unavailable.
    }
  }

  // ── Pairing object helpers ───────────────────────────────────────────────

  void _applyPairingObject(PairingObject pairing) {
    _gatewayUrlController.text = pairing.gatewayUrl;
    _pairingCodeController.text = pairing.code;
    _expiryTimer?.cancel();
    setState(() {
      _parsedPairing = pairing;
      // Rebuild every second so the countdown stays fresh.
      _expiryTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    });
  }

  // ── Paste from clipboard ─────────────────────────────────────────────────

  Future<void> _pasteFromClipboard() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text?.trim();
    if (text == null || text.isEmpty) {
      _showSnackBar(AppStrings.pasteClipboardEmpty);
      return;
    }
    _parsePairingJson(text, errorMessage: AppStrings.pasteInvalidJson);
  }

  // ── QR scanner ───────────────────────────────────────────────────────────

  Future<void> _openQrScanner() async {
    final raw = await context.push<String?>(RouteNames.qrScan);
    if (raw == QrScanScreen.permissionDeniedMarker) {
      // User denied camera — hide button for this session.
      setState(() => _showQrButton = false);
      return;
    }
    if (raw == null) return; // User cancelled.
    _parsePairingJson(raw, errorMessage: AppStrings.qrInvalidJson);
  }

  // ── JSON parse ───────────────────────────────────────────────────────────

  void _parsePairingJson(String raw, {required String errorMessage}) {
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      final pairing = PairingObject.fromJson(json);
      _applyPairingObject(pairing);
    } catch (_) {
      _showSnackBar(errorMessage);
    }
  }

  // ── Connect ──────────────────────────────────────────────────────────────

  Future<void> _connect() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final nameRaw = _deviceNameController.text.trim();
    await ref.read(authProvider.notifier).pair(
          _gatewayUrlController.text.trim(),
          _pairingCodeController.text.trim(),
          deviceName: nameRaw.isEmpty ? null : nameRaw,
        );
  }

  void _showSnackBar(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final authAsync = ref.watch(authProvider);
    final isPairing = authAsync.value is AuthPairing;
    final errorMsg = authAsync.value is AuthError
        ? (authAsync.value! as AuthError).message
        : null;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _HiroBranding(),
                  const SizedBox(height: 40),
                  Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextFormField(
                          controller: _deviceNameController,
                          enabled: !isPairing,
                          decoration: const InputDecoration(
                            labelText: 'Device Name',
                            hintText: 'Name shown in the admin device list',
                            prefixIcon: Icon(Icons.smartphone_rounded),
                            border: OutlineInputBorder(),
                          ),
                          maxLength: 64,
                          buildCounter: (_, {required currentLength, required isFocused, maxLength}) => null,
                        ),
                        const SizedBox(height: 16),
                        GatewayUrlField(
                          controller: _gatewayUrlController,
                          enabled: !isPairing,
                        ),
                        const SizedBox(height: 16),
                        PairingCodeField(
                          controller: _pairingCodeController,
                          enabled: !isPairing,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  // Paste button — standalone, below the two input fields.
                  OutlinedButton.icon(
                    onPressed: isPairing ? null : _pasteFromClipboard,
                    icon: const Icon(Icons.content_paste_rounded),
                    label: const Text(AppStrings.pastePairingObject),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(48),
                    ),
                  ),
                  if (_parsedPairing != null) ...[
                    const SizedBox(height: 10),
                    _ExpiryBadge(pairing: _parsedPairing!),
                  ],
                  if (errorMsg != null) ...[
                    const SizedBox(height: 16),
                    _ErrorBanner(message: errorMsg),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: isPairing ? null : _connect,
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                    ),
                    child: isPairing
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              color: Colors.white,
                            ),
                          )
                        : const Text('Connect'),
                  ),
                  if (_showQrButton) ...[
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: isPairing ? null : _openQrScanner,
                      icon: const Icon(Icons.qr_code_scanner_rounded),
                      label: const Text(AppStrings.qrScanButton),
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size.fromHeight(48),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Private widgets ──────────────────────────────────────────────────────────

class _HiroBranding extends StatelessWidget {
  const _HiroBranding();

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      children: [
        Container(
          width: 80,
          height: 80,
          decoration: BoxDecoration(
            color: cs.primaryContainer,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Icon(Icons.home_rounded, size: 44, color: cs.primary),
        ),
        const SizedBox(height: 20),
        Text(
          AppStrings.appName,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: cs.primary,
                fontWeight: FontWeight.w700,
              ),
        ),
        const SizedBox(height: 8),
        Text(
          'Connect to your gateway to get started',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: cs.onSurfaceVariant,
              ),
        ),
      ],
    );
  }
}

class _ExpiryBadge extends StatelessWidget {
  const _ExpiryBadge({required this.pairing});

  final PairingObject pairing;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now().toUtc();
    final diff = pairing.expiresAt.toUtc().difference(now);
    final isExpired = diff.isNegative;

    final cs = Theme.of(context).colorScheme;
    final bgColor = isExpired ? cs.errorContainer : cs.secondaryContainer;
    final fgColor = isExpired ? cs.onErrorContainer : cs.onSecondaryContainer;
    final icon = isExpired ? Icons.timer_off_rounded : Icons.timer_rounded;

    final String label;
    if (isExpired) {
      final ago = now.difference(pairing.expiresAt.toUtc());
      label = '${AppStrings.pairingExpired} ${_formatDuration(ago)} ago';
    } else {
      label = '${AppStrings.pairingExpiresIn} ${_formatDuration(diff)}';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: fgColor),
          const SizedBox(width: 6),
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: fgColor),
          ),
        ],
      ),
    );
  }

  String _formatDuration(Duration d) {
    if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes.remainder(60)}m';
    if (d.inMinutes > 0) {
      return '${d.inMinutes}m ${d.inSeconds.remainder(60)}s';
    }
    return '${d.inSeconds}s';
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: cs.errorContainer,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline_rounded, color: cs.onErrorContainer, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: cs.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}
