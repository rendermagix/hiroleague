import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'controllers/app_controller.dart';
import 'screens/chat_screen.dart';
import 'screens/pairing_screen.dart';
import 'services/crypto_service.dart';
import 'services/gateway_service.dart';
import 'services/storage_service.dart';

void main() {
  runApp(const PhbMobileApp());
}

class PhbMobileApp extends StatelessWidget {
  const PhbMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<AppController>(
      create: (_) {
        final cryptoService = CryptoService();
        final controller = AppController(
          storageService: StorageService(),
          cryptoService: cryptoService,
          gatewayService: GatewayService(cryptoService),
        );
        controller.init();
        return controller;
      },
      child: MaterialApp(
        title: 'Private Home Box',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
          useMaterial3: true,
        ),
        home: const _RootScreen(),
      ),
    );
  }
}

class _RootScreen extends StatelessWidget {
  const _RootScreen();

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppController>();
    if (!app.initialized) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }
    final paired = app.identity?.attestation != null;
    return paired ? const ChatScreen() : const PairingScreen();
  }
}
