import { defineConfig } from 'astro/config';
import { CUSTOM_DOMAIN, BASE_PATH } from './src/server-constants.ts';
import CoverImageDownloader from './src/integrations/cover-image-downloader';
import CustomIconDownloader from './src/integrations/custom-icon-downloader';
import FeaturedImageDownloader from './src/integrations/featured-image-downloader';
import PublicNotionCopier from './src/integrations/public-notion-copier';

// https://astro.build/config
export default defineConfig({
  site: CUSTOM_DOMAIN || 'https://dicyzz.github.io',
  base: BASE_PATH || '',
  integrations: [
    CoverImageDownloader(),
    CustomIconDownloader(),
    FeaturedImageDownloader(),
    PublicNotionCopier(),
  ],
});
