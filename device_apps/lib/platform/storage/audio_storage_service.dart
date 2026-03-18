import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import 'audio_fetch.dart';

part 'audio_storage_service.g.dart';

/// Handles platform-aware persistence of audio recordings.
///
/// - Mobile (iOS/Android): Persists to `<documents>/audio/<messageId>.m4a`.
///   Audio survives app restarts.
/// - Web: Stores the blob URL returned by the record package. Audio lives in
///   the browser's memory and is valid for the current page session.
class AudioStorageService {
  static const _audioSubdir = 'audio';

  /// Saves a recording for [messageId] and returns the playback source.
  ///
  /// On mobile, copies from [tempPath] to persistent storage and returns the
  /// persistent file path.
  /// On web, [blobUrl] is already the playback source — returns it directly.
  Future<String> save({
    required String messageId,
    required Uint8List bytes,
    required String tempPath,
    String blobUrl = '',
  }) async {
    if (kIsWeb) {
      return blobUrl.isNotEmpty ? blobUrl : tempPath;
    }

    final dir = await _audioDir();
    final dest = File('${dir.path}/$messageId.m4a');

    if (bytes.isNotEmpty) {
      await dest.writeAsBytes(bytes, flush: true);
    } else if (tempPath.isNotEmpty) {
      final src = File(tempPath);
      if (await src.exists()) {
        await src.copy(dest.path);
      }
    }
    return dest.path;
  }

  /// Saves raw bytes directly to persistent storage and returns the file path.
  /// Used when receiving inbound audio from the server (decoded from base64).
  Future<String> saveBytes({
    required String messageId,
    required Uint8List bytes,
  }) async {
    if (kIsWeb) {
      // On web, create a data URI for immediate playback (no persistent storage).
      final b64 = base64Encode(bytes);
      return 'data:audio/m4a;base64,$b64';
    }

    final dir = await _audioDir();
    final file = File('${dir.path}/$messageId.m4a');
    await file.writeAsBytes(bytes, flush: true);
    return file.path;
  }

  /// Returns the bytes of a stored audio file.
  ///
  /// On mobile: reads from the file system.
  /// On web: fetches bytes from the blob or data URL via the browser's fetch API.
  /// Returns null if the source is unavailable.
  Future<Uint8List?> loadBytes(String localPath) async {
    if (localPath.isEmpty) return null;
    if (kIsWeb) {
      return fetchAudioBytes(localPath);
    }
    final file = File(localPath);
    if (!await file.exists()) return null;
    return file.readAsBytes();
  }

  /// Deletes a stored audio file (mobile only).
  Future<void> delete(String localPath) async {
    if (kIsWeb || localPath.isEmpty) return;
    final file = File(localPath);
    if (await file.exists()) await file.delete();
  }

  Future<Directory> _audioDir() async {
    final docs = await getApplicationDocumentsDirectory();
    final dir = Directory('${docs.path}/$_audioSubdir');
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir;
  }
}

// keepAlive: stateless singleton — cheap to keep alive, avoids recreation.
@Riverpod(keepAlive: true)
AudioStorageService audioStorage(Ref ref) => AudioStorageService();
