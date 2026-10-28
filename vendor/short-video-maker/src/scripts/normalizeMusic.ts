import ffmpeg from "fluent-ffmpeg";
import path from "path";
import("@ffmpeg-installer/ffmpeg");
import fs from "fs-extra";

import { logger } from "../logger";
import { MusicManager } from "../short-creator/music";
import { Config } from "../config";

async function normalize(inputPath: string, outputPath: string) {
  return new Promise((resolve, reject) => {
    ffmpeg()
      .input(inputPath)
      .audioCodec("libmp3lame")
      .audioBitrate(96)
      .audioChannels(2)
      .audioFrequency(44100)
      .audioFilter("loudnorm,volume=0.1")
      .toFormat("mp3")
      .on("error", (err) => {
        logger.error(err, "Error normalizing audio:");
        reject(err);
      })
      .save(outputPath)
      .on("end", () => {
        logger.debug("Audio normalization complete");
        resolve(outputPath);
      });
  });
}

export async function normalizeMusic() {
  const config = new Config();
  const musicManager = new MusicManager(config);
  try {
    musicManager.ensureMusicFilesExist();
  } catch (error: unknown) {
    logger.error(error, "Missing music files");
    process.exit(1);
  }
  const musicFiles = musicManager.musicList();
  const normalizedDir = path.join(config.musicDirPath, "normalized");
  fs.ensureDirSync(normalizedDir);
  for (const musicFile of musicFiles) {
    const inputPath = path.join(config.musicDirPath, musicFile.file);
    const outputPath = path.join(normalizedDir, musicFile.file);
    logger.debug({ inputPath, outputPath }, "Normalizing music file");
    await normalize(inputPath, outputPath);
  }
}

normalizeMusic()
  .then(() => {
    logger.info(
      "Music normalization completed successfully - make sure to replace the original files with the normalized ones",
    );
  })
  .catch((error: unknown) => {
    logger.error(error, "Error normalizing music files");
  });
