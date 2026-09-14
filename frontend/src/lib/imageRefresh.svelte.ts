/**
 * Auto-retry for a trip card's cover image.
 *
 * A card whose photo 404s asks the server for a different one **once**, then
 * gives up and shows the fallback glyph — retrying on every render would hammer
 * Wikipedia for a trip that simply has no photo.
 *
 * Manual refresh is not here: that control lives inside the trip, where the
 * image is large enough to judge. On a card it covered a third of the photo.
 *
 * Usage:
 *   const imgRefresh = new ImageRefreshManager();
 *   // in template: imgFailed={imgRefresh.imgFailed[trip.id] ?? false}
 *                  onImageError={(e) => imgRefresh.handleError(e, trip.id)}
 */
import { tripsApi } from '../api/client';
import { tripImageBust } from './tripImageStore';

export class ImageRefreshManager {
  imgFailed = $state<Record<string, boolean>>({});
  private retried = new Set<string>();

  async handleError(_e: Event, tripId: string) {
    if (this.retried.has(tripId)) {
      this.imgFailed = { ...this.imgFailed, [tripId]: true };
      return;
    }
    this.retried.add(tripId);
    try {
      await tripsApi.refreshImage(tripId);
      tripImageBust.bust(tripId);
    } catch {
      this.imgFailed = { ...this.imgFailed, [tripId]: true };
    }
  }
}
