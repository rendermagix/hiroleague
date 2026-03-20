import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// Probes the browser MediaDevices API for audio input hardware.
/// Returns false only when the browser confirms zero audioinput devices.
Future<bool> hasMicDevice() async {
  try {
    final devices =
        await web.window.navigator.mediaDevices.enumerateDevices().toDart;
    return devices.toDart.any((d) => d.kind == 'audioinput');
  } catch (_) {
    // API unavailable — assume mic exists so the normal flow continues.
    return true;
  }
}
