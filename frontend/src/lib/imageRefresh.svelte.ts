/**
 * Reactive image refresh manager for trip cards.
 * Handles auto-retry on error and manual refresh via the trips API.
 *
 * Usage:
 *   const imgRefresh = new ImageRefreshManager();
 *   // in template: imgFailed={imgRefresh.imgFailed[trip.id] ?? false}
 *                  onImageError={(e) => imgRefresh.handleError(e, trip.id)}
 *                  onRefreshImage={(e) => imgRefresh.refresh(e, trip.id)}
 */
import { tripsApi } from '../api/client';
import { tripImageBust } from './tripImageStore';

export class ImageRefreshManager {
  refreshingId = $state<string | null>(null);
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

  async refresh(e: MouseEvent, tripId: string) {
    e.preventDefault();
    e.stopPropagation();
    this.refreshingId = tripId;
    try {
      await tripsApi.refreshImage(tripId);
      this.imgFailed = { ...this.imgFailed, [tripId]: false };
      this.retried.delete(tripId);
      tripImageBust.bust(tripId);
    } catch {
      // no image available — leave current state
    } finally {
      this.refreshingId = null;
    }
  }
}
