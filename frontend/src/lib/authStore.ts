/**
 * Global auth store — holds the current logged-in user.
 */
import { writable } from 'svelte/store';
import type { User } from '../api/types';

export const currentUser = writable<User | null>(null);
export const authLoading = writable<boolean>(true);
