import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/chat_message.dart';
import '../models/device_identity.dart';
import '../services/crypto_service.dart';
import '../services/gateway_service.dart';
import '../services/storage_service.dart';

class AppController extends ChangeNotifier {
  AppController({
    required StorageService storageService,
    required CryptoService cryptoService,
    required GatewayService gatewayService,
  })  : _storageService = storageService,
        _cryptoService = cryptoService,
        _gatewayService = gatewayService;

  final StorageService _storageService;
  final CryptoService _cryptoService;
  final GatewayService _gatewayService;

  DeviceIdentity? _identity;
  DeviceIdentity? get identity => _identity;

  final List<ChatMessage> _messages = <ChatMessage>[];
  List<ChatMessage> get messages => List<ChatMessage>.unmodifiable(_messages);

  GatewayConnectionState _connectionState = GatewayConnectionState.disconnected;
  GatewayConnectionState get connectionState => _connectionState;

  String? _error;
  String? get error => _error;

  bool _busy = false;
  bool get busy => _busy;

  bool _initialized = false;
  bool get initialized => _initialized;

  StreamSubscription<ChatMessage>? _messageSub;
  StreamSubscription<GatewayConnectionState>? _stateSub;

  Future<void> init() async {
    _identity = await _storageService.loadIdentity();
    _listenGatewayStreams();
    if (_identity?.attestation != null) {
      await reconnect();
    }
    _initialized = true;
    notifyListeners();
  }

  Future<void> startPairing({
    required String gatewayUrl,
    required String pairingCode,
  }) async {
    _setBusy(true);
    _error = null;
    try {
      final loaded = _identity ?? await _storageService.loadIdentity();
      final workingIdentity = loaded == null
          ? await _createIdentity(gatewayUrl)
          : loaded.copyWith(gatewayUrl: gatewayUrl);
      final result = await _gatewayService.pairDevice(
        identity: workingIdentity,
        pairingCode: pairingCode,
      );
      final updated = workingIdentity.copyWith(
        attestation: result.attestation,
        desktopDeviceId: result.desktopDeviceId,
      );
      _identity = updated;
      await _storageService.saveIdentity(updated);
      await reconnect();
    } catch (e) {
      _error = e.toString();
    } finally {
      _setBusy(false);
    }
    notifyListeners();
  }

  Future<void> reconnect() async {
    final identity = _identity ?? await _storageService.loadIdentity();
    if (identity == null || identity.attestation == null) {
      return;
    }
    _error = null;
    try {
      await _gatewayService.connectAuthenticated(identity);
    } catch (e) {
      _error = e.toString();
    }
    notifyListeners();
  }

  Future<void> sendText(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) {
      return;
    }
    final identity = _identity;
    if (identity == null) {
      _error = 'Device is not paired';
      notifyListeners();
      return;
    }
    try {
      await _gatewayService.sendText(
        text: trimmed,
        senderId: identity.deviceId,
        recipientId: identity.desktopDeviceId,
      );
      _messages.add(
        ChatMessage(
          id: DateTime.now().microsecondsSinceEpoch.toString(),
          body: trimmed,
          senderId: identity.deviceId,
          timestamp: DateTime.now().toUtc(),
          isOutbound: true,
        ),
      );
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> unpair() async {
    await _gatewayService.disconnect();
    _messages.clear();
    _identity = null;
    _error = null;
    _connectionState = GatewayConnectionState.disconnected;
    await _storageService.clearAll();
    notifyListeners();
  }

  @override
  void dispose() {
    _messageSub?.cancel();
    _stateSub?.cancel();
    _gatewayService.dispose();
    super.dispose();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  Future<DeviceIdentity> _createIdentity(String gatewayUrl) async {
    final generated = await _cryptoService.generateIdentity();
    final identity = DeviceIdentity(
      deviceId: generated.deviceId,
      seedBase64: generated.seedBase64,
      publicKeyBase64: generated.publicKeyBase64,
      gatewayUrl: gatewayUrl,
    );
    _identity = identity;
    await _storageService.saveIdentity(identity);
    return identity;
  }

  void _listenGatewayStreams() {
    _messageSub?.cancel();
    _stateSub?.cancel();
    _messageSub = _gatewayService.messages.listen((ChatMessage message) {
      _messages.add(message);
      notifyListeners();
    });
    _stateSub = _gatewayService.states.listen((GatewayConnectionState state) {
      _connectionState = state;
      notifyListeners();
    });
  }

  void _setBusy(bool value) {
    _busy = value;
    notifyListeners();
  }
}
