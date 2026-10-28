# Contributing to Shorts Creator

## How to setup the development environment

1. Clone the repository

   ```bash
   git clone git@github.com:gyoridavid/short-video-maker.git
   cd shorts-video-maker
   ```

2. Install dependencies

   ```bash
   pnpm install
   ```

3. Copy `.env.example` to `.env` and set the right environment variables.

4. Start the server
   ```bash
   pnpm dev
   ```

## How to preview the videos and debug the rendering process

You can use Remotion Studio to preview videos. Make sure to update the template if the underlying data structure changes.

```bash
npx remotion studio
```
