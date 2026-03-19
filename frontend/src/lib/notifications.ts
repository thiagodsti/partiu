/**
 * Browser-side Web Push helpers.
 *
 * subscribe()   — request permission, get subscription, POST to backend
 * unsubscribe() — remove subscription from browser + backend
 * isSupported() — true if Push API is available
 * getStatus()   — 'unsupported' | 'denied' | 'default' | 'subscribed' | 'unsubscribed'
 */

import { notificationsApi } from '../api/client';

export type NotifStatus = 'unsupported' | 'denied' | 'default' | 'subscribed' | 'unsubscribed';

export function isSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const arr = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i);
  return arr.buffer;
}

export async function getStatus(): Promise<NotifStatus> {
  if (!isSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';

  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) return 'subscribed';
  if (Notification.permission === 'granted') return 'unsubscribed';
  return 'default';
}

export async function subscribe(): Promise<boolean> {
  if (!isSupported()) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  let publicKey: string;
  try {
    const data = await notificationsApi.vapidPublicKey();
    publicKey = data.public_key;
  } catch {
    return false;
  }

  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });

  await notificationsApi.subscribe(subscription.toJSON());
  return true;
}

export async function unsubscribe(): Promise<boolean> {
  if (!isSupported()) return false;

  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  if (!subscription) return true;

  await notificationsApi.unsubscribe(subscription.endpoint);
  await subscription.unsubscribe();
  return true;
}
