import '../models/identity/device_identity.dart';

/// Contract for identity persistence and pairing.
/// Implementations live in data/repositories/.
abstract class AuthRepository {
  /// Returns the stored identity, or null if the device has never paired.
  Future<DeviceIdentity?> loadIdentity();

  /// Persists an identity (after successful pairing).
  Future<void> saveIdentity(DeviceIdentity identity);

  /// Removes the stored identity (unpairing / factory reset).
  Future<void> clearIdentity();

  /// Connects to [gatewayUrl], runs the pairing handshake with [pairingCode],
  /// and returns the paired [DeviceIdentity] with a valid attestation.
  ///
  /// Throws [PairingException] on rejection or timeout.
  /// Throws [GatewayException] on WebSocket errors.
  Future<DeviceIdentity> pairDevice({
    required String gatewayUrl,
    required String pairingCode,
    String? deviceName,
  });
}
