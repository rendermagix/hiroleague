import 'package:freezed_annotation/freezed_annotation.dart';

import 'attestation.dart';

part 'device_identity.freezed.dart';
part 'device_identity.g.dart';

@freezed
abstract class DeviceIdentity with _$DeviceIdentity {
  // fieldRename: snake maps all camelCase fields to snake_case for storage and protocol.
  // e.g. deviceId ↔ device_id, desktopDeviceId ↔ desktop_device_id
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory DeviceIdentity({
    required String deviceId,
    required String seedBase64,
    required String publicKeyBase64,
    required String gatewayUrl,
    // Null until the device completes pairing.
    DeviceAttestation? attestation,
    // Set by the server on pairing approval; may be null if not provided.
    String? desktopDeviceId,
    // Human-readable name shown in the admin device list.
    String? deviceName,
  }) = _DeviceIdentity;

  factory DeviceIdentity.fromJson(Map<String, dynamic> json) =>
      _$DeviceIdentityFromJson(json);
}
