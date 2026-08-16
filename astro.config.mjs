import { defineConfig } from 'astro/config';
import astroIcon from 'astro-icon';
import { CUSTOM_DOMAIN, BASE_PATH } from './src/server-constants.ts';
import CoverImageDownloader from './src/integrations/cover-image-downloader';
import CustomIconDownloader from './src/integrations/custom-icon-downloader';
import FeaturedImageDownloader from './src/integrations/featured-image-downloader';
import PublicNotionCopier from './src/integrations/public-notion-copier';

// https://astro.build/config
export default defineConfig({
  site: CUSTOM_DOMAIN || 'https://zhangjian0248.top',
  base: BASE_PATH || '/blog',
  integrations: [
    astroIcon(),
    CoverImageDownloader(),
    CustomIconDownloader(),
    FeaturedImageDownloader(),
    PublicNotionCopier(),
  ],
});
