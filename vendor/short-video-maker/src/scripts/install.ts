import { ensureBrowser } from "@remotion/renderer";

import { logger } from "../logger";
import { Kokoro } from "../short-creator/libraries/Kokoro";
import { MusicManager } from "../short-creator/music";
import { Config } from "../config";
import { Whisper } from "../short-creator/libraries/Whisper";

// runs in docker
export async function install() {
  const config = new Config();

  logger.info("Installing dependencies...");
  logger.info("Installing Kokoro...");
  await Kokoro.init(config.kokoroModelPrecision);
  logger.info("Installing browser shell...");
  await ensureBrowser();
  logger.info("Installing whisper.cpp");
  await Whisper.init(config);
  logger.info("Installing dependencies complete");

  logger.info("Ensuring the music files exist...");
  const musicManager = new MusicManager(config);
  try {
    musicManager.ensureMusicFilesExist();
  } catch (error: unknown) {
    logger.error(error, "Missing music files");
    process.exit(1);
  }
}

install()
  .then(() => {
    logger.info("Installation complete");
  })
  .catch((error: unknown) => {
    logger.error(error, "Installation failed");
  });
