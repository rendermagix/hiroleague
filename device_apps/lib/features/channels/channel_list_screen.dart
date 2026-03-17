import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../application/channels/channels_notifier.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../application/gateway/gateway_state.dart';
import '../../core/constants/app_strings.dart';
import '../../domain/models/channel/channel.dart';

class ChannelListScreen extends ConsumerWidget {
  const ChannelListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final gateway = ref.watch(gatewayProvider);
    final channelsAsync = ref.watch(channelsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text(AppStrings.navChannels),
        actions: [_GatewayStatusChip(gateway: gateway)],
      ),
      body: channelsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text(
            'Failed to load channels',
            style: TextStyle(
              color: Theme.of(context).colorScheme.error,
            ),
          ),
        ),
        data: (channels) {
          if (channels.isEmpty) {
            return const Center(child: CircularProgressIndicator());
          }
          if (channels.length == 1) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              context.go('/app/channels/${channels.first.id}');
            });
            return const Center(child: CircularProgressIndicator());
          }
          return ListView.separated(
            itemCount: channels.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, index) =>
                _ChannelTile(channel: channels[index]),
          );
        },
      ),
    );
  }
}

class _ChannelTile extends StatelessWidget {
  const _ChannelTile({required this.channel});

  final Channel channel;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: cs.primaryContainer,
        foregroundColor: cs.onPrimaryContainer,
        child: Text(
          channel.name.isNotEmpty
              ? channel.name[0].toUpperCase()
              : '#',
        ),
      ),
      title: Text(channel.name),
      trailing: const Icon(Icons.chevron_right_rounded),
      onTap: () => context.push('/app/channels/${channel.id}'),
    );
  }
}

class _GatewayStatusChip extends StatelessWidget {
  const _GatewayStatusChip({required this.gateway});

  final GatewayState gateway;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(right: 16),
      child: gateway.when(
        disconnected: () =>
            Icon(Icons.cloud_off_rounded, color: cs.outline),
        connecting: () => SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(
              strokeWidth: 2, color: cs.primary),
        ),
        connected: (_) =>
            Icon(Icons.cloud_done_rounded, color: Colors.green.shade600),
        error: (_) =>
            Icon(Icons.cloud_off_rounded, color: cs.error),
      ),
    );
  }
}
