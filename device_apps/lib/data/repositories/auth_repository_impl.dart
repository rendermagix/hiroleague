import 'dart:convert';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/constants/storage_keys.dart';
import '../../core/errors/app_exception.dart';
import '../../core/utils/logger.dart';
import '../../domain/models/identity/device_identity.dart';
import '../../domain/repositories/auth_repository.dart';
import '../../domain/services/crypto_service.dart';
import '../../platform/storage/secure_storage_service.dart';
import '../remote/pairing/pairing_client.dart';

part 'auth_repository_impl.g.dart';

@Riverpod(keepAlive: true)
AuthRepository authRepository(Ref ref) => AuthRepositoryImpl(
      storageService: ref.watch(secureStorageServiceProvider),
    );

class AuthRepositoryImpl implements AuthRepository {
  AuthRepositoryImpl({required this.storageService})
      : _cryptoService = CryptoService(),
        _pairingClient = PairingClient(CryptoService());

  final SecureStorageService storageService;
  final CryptoService _cryptoService;
  final PairingClient _pairingClient;
  final _log = Logger.get('AuthRepository');

  @override
  Future<DeviceIdentity?> loadIdentity() async {
    try {
      final raw = await storageService.read(StorageKeys.deviceIdentity);
      if (raw == null) return null;
      return DeviceIdentity.fromJson(
        (jsonDecode(raw) as Map).cast<String, dynamic>(),
      );
    } catch (e) {
      _log.error('Failed to load identity', error: e);
      return null;
    }
  }

  @override
  Future<void> saveIdentity(DeviceIdentity identity) async {
    try {
      await storageService.write(
        StorageKeys.deviceIdentity,
        jsonEncode(identity.toJson()),
      );
    } catch (e) {
      throw StorageException('Failed to save identity: $e');
    }
  }

  @override
  Future<void> clearIdentity() async {
    try {
      await storageService.delete(StorageKeys.deviceIdentity);
    } catch (e) {
      throw StorageException('Failed to clear identity: $e');
    }
  }

  @override
  Future<DeviceIdentity> pairDevice({
    required String gatewayUrl,
    required String pairingCode,
    String? deviceName,
  }) async {
    // Generate or reuse keypair.
    // On first pairing, we always generate a fresh keypair.
    // If pairing fails and user retries, they get the same deviceId (loaded from storage).
    DeviceIdentity unpaired;
    final existing = await loadIdentity();
    if (existing != null && existing.attestation == null) {
      // Reuse the unpaired identity from a previous failed attempt, but update
      // the device name if a new one was provided.
      unpaired = existing.copyWith(
        gatewayUrl: gatewayUrl,
        deviceName: deviceName ?? existing.deviceName,
      );
    } else {
      final keypair = await _cryptoService.generateKeypair();
      unpaired = DeviceIdentity(
        deviceId: keypair.deviceId,
        seedBase64: keypair.seedBase64,
        publicKeyBase64: keypair.publicKeyBase64,
        gatewayUrl: gatewayUrl,
        deviceName: deviceName,
      );
    }

    // Save the unpaired identity so we can resume on crash/retry
    await saveIdentity(unpaired);

    final attestation = await _pairingClient.pair(
      gatewayUrl: gatewayUrl,
      deviceId: unpaired.deviceId,
      seedBase64: unpaired.seedBase64,
      publicKeyBase64: unpaired.publicKeyBase64,
      pairingCode: pairingCode,
      deviceName: unpaired.deviceName,
    );

    final paired = unpaired.copyWith(attestation: attestation);
    await saveIdentity(paired);
    _log.info('Identity saved after pairing', fields: {'deviceId': paired.deviceId});
    return paired;
  }
}
