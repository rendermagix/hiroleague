import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/constants/app_constants.dart';
import '../../../core/errors/app_exception.dart';
import '../../../core/utils/logger.dart';
import '../../../domain/models/identity/attestation.dart';
import '../../../domain/services/crypto_service.dart';

/// Minimal WebSocket client for the pairing handshake only.
/// Not used after pairing — the full GatewayClient (Gateway phase) takes over.
///
/// Protocol:
///   Server → Client: auth_challenge { nonce }
///   Client → Server: pairing_request { pairing_code, device_public_key, device_id, nonce_signature }
///   Server → Client: pairing_pending { request_id }   (ignored)
///   Server → Client: pairing_response { status, attestation? }
class PairingClient {
  PairingClient(this._cryptoService);

  final CryptoService _cryptoService;
  final _log = Logger.get('PairingClient');

  /// Runs the full pairing handshake.
  /// Returns a [DeviceAttestation] on success.
  /// Throws [PairingException] or [GatewayException] on failure.
  Future<DeviceAttestation> pair({
    required String gatewayUrl,
    required String deviceId,
    required String seedBase64,
    required String publicKeyBase64,
    required String pairingCode,
    String? deviceName,
  }) async {
    _log.info('Starting pairing', fields: {'url': gatewayUrl});

    WebSocketChannel? channel;
    try {
      channel = WebSocketChannel.connect(Uri.parse(gatewayUrl));

      // In web_socket_channel 3.x, channel.ready must be awaited before the
      // stream is used. If the TCP connection fails or is blocked, ready rejects
      // quickly (or after our timeout) rather than leaving the stream silently
      // pending — which would cause the finally-block sink.close() to hang forever
      // because foreignToLocalController.stream never gets a listener.
      await channel.ready.timeout(
        AppConstants.authTimeout,
        onTimeout: () => throw const GatewayException('Connection timed out'),
      );

      final stream = channel.stream.asBroadcastStream();

      // 1 — Wait for auth_challenge
      final nonce = await _awaitChallenge(stream);
      _log.debug('Got auth challenge');

      // 2 — Sign the nonce and send pairing_request
      final nonceSignature = await _cryptoService.signNonce(seedBase64, nonce);
      final pairingRequest = <String, dynamic>{
        'type': 'pairing_request',
        'pairing_code': pairingCode,
        'device_public_key': publicKeyBase64,
        'device_id': deviceId,
        'nonce_signature': nonceSignature,
      };
      // Include device_name so the server can label the device in the admin UI.
      if (deviceName != null && deviceName.isNotEmpty) {
        pairingRequest['device_name'] = deviceName;
      }
      channel.sink.add(jsonEncode(pairingRequest));
      _log.debug('Sent pairing_request');

      // 3 — Wait for pairing_response (ignore pairing_pending)
      final response = await stream
          .map(_toMap)
          .firstWhere(
            (m) => m != null && m['type']?.toString() == 'pairing_response',
          )
          .timeout(
            AppConstants.pairingTimeout,
            onTimeout: () => throw const PairingException('Timed out waiting for pairing approval'),
          );

      final status = response?['status']?.toString();
      if (status != 'approved') {
        final reason = response?['reason']?.toString() ?? 'Pairing was rejected';
        throw PairingException(reason);
      }

      final attJson = (response?['attestation'] as Map?)?.cast<String, dynamic>();
      if (attJson == null || attJson.isEmpty) {
        throw const PairingException('Pairing response missing attestation');
      }

      final attestation = DeviceAttestation.fromJson(attJson);
      if (attestation.blob.isEmpty || attestation.desktopSignature.isEmpty) {
        throw const PairingException('Attestation is incomplete');
      }

      _log.info('Pairing successful', fields: {'deviceId': deviceId});
      return attestation;
    } on PairingException {
      rethrow;
    } on GatewayException {
      rethrow;
    } on TimeoutException catch (e) {
      throw PairingException('Timeout: ${e.message}');
    } catch (e) {
      throw GatewayException('WebSocket error: $e');
    } finally {
      // Do not await sink.close() — if the WebSocket future never resolved
      // (blocked IP), the underlying stream has no listener and sink.done never
      // completes, causing a permanent hang.
      channel?.sink.close();
    }
  }

  Future<String> _awaitChallenge(Stream<dynamic> stream) async {
    Map<String, dynamic>? challengeMsg;
    try {
      challengeMsg = await stream
          .map(_toMap)
          .firstWhere((m) => m != null && m['type']?.toString() == 'auth_challenge')
          .timeout(
            AppConstants.authTimeout,
            onTimeout: () =>
                throw const GatewayException('Timed out waiting for auth challenge'),
          );
    } on StateError {
      throw const GatewayException('Gateway closed before auth challenge');
    }

    final nonce = challengeMsg?['nonce']?.toString() ?? '';
    if (nonce.isEmpty) throw const GatewayException('Auth challenge missing nonce');
    return nonce;
  }

  Map<String, dynamic>? _toMap(dynamic raw) {
    if (raw is! String) return null;
    try {
      return (jsonDecode(raw) as Map).cast<String, dynamic>();
    } catch (_) {
      return null;
    }
  }
}
