import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/errors/app_exception.dart';
import '../../data/repositories/auth_repository_impl.dart';
import 'auth_state.dart';

part 'auth_notifier.g.dart';

@riverpod
class AuthNotifier extends _$AuthNotifier {
  @override
  Future<AuthState> build() async {
    final repo = ref.watch(authRepositoryProvider);
    final identity = await repo.loadIdentity();
    if (identity?.attestation != null) {
      return AuthState.authenticated(identity!);
    }
    return const AuthState.unauthenticated();
  }

  /// Initiates the pairing handshake.
  Future<void> pair(String gatewayUrl, String pairingCode, {String? deviceName}) async {
    state = const AsyncData(AuthState.pairing());
    try {
      final repo = ref.read(authRepositoryProvider);
      final identity = await repo.pairDevice(
        gatewayUrl: gatewayUrl,
        pairingCode: pairingCode,
        deviceName: deviceName,
      );
      state = AsyncData(AuthState.authenticated(identity));
    } on AppException catch (e) {
      state = AsyncData(AuthState.error(e.message));
    } catch (e) {
      state = AsyncData(AuthState.error(e.toString()));
    }
  }

  /// Removes the stored identity (user-initiated unpair / factory reset).
  Future<void> unpair() async {
    final repo = ref.read(authRepositoryProvider);
    await repo.clearIdentity();
    state = const AsyncData(AuthState.unauthenticated());
  }
}
