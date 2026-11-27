/**
 * Every account the E2E suite signs in as, in one place.
 *
 * `global-setup.ts` creates all of them before the first spec runs. Specs used
 * to bootstrap their own users through first-run setup, which only the first
 * spec to run on an empty server can do — every other one got a 409, failed to
 * sign in, and skipped, so a fresh CI server ran almost nothing. A spec needing
 * a new account adds it here, not as a string of its own.
 */

export interface E2EAccount {
  username: string;
  password: string;
  admin?: boolean;
}

/** Creates the others. Made through first-run setup on an empty server. */
export const E2E_ADMIN: E2EAccount = { username: 'e2e_admin', password: 'E2eAdmin1!', admin: true };

/** Owns the seeded trip that the browse-only specs open (see `seed.ts`). */
export const E2E_BROWSER: E2EAccount = { username: 'e2e_browser', password: 'E2eBrowser1!' };

export const ACCOUNTS = {
  apiKeysUser: { username: 'e2e_api_keys_user', password: 'E2eApiKeysUser1!' },
  bookingCarUser: { username: 'e2e_booking_car_user', password: 'E2eBookingCarUser1!' },
  integrationsAdmin: { username: 'e2e_integrations_admin', password: 'E2eIntegrations1!', admin: true },
  blockedRegular: { username: 'e2e_blocked_regular', password: 'E2eBlockedRegular1!' },
  budgetOwner: { username: 'e2e_budget_owner', password: 'E2eBudgetOwner1!' },
  budgetPartner: { username: 'e2e_budget_partner', password: 'E2eBudgetPartner1!' },
  cancelUser: { username: 'e2e_cancel_user', password: 'E2eCancelUser1!' },
  docGuest: { username: 'e2e_doc_guest', password: 'E2eDocGuest1!' },
  docOwner: { username: 'e2e_doc_owner', password: 'E2eDocOwner1!' },
  emlUser: { username: 'e2e_eml_user', password: 'E2eEmlUser1!' },
  feditOther: { username: 'e2e_fedit_other', password: 'E2eFeditOther1!' },
  feditOwner: { username: 'e2e_fedit_owner', password: 'E2eFeditOwner1!' },
  forwardUser: { username: 'e2e_forward_user', password: 'E2eForwardUser1!' },
  kitUser: { username: 'e2e_kit_user', password: 'E2eKitUser1!' },
  lodgingUser: { username: 'e2e_lodging_user', password: 'E2eLodgingUser1!' },
  planOwner: { username: 'e2e_plan_owner', password: 'E2ePlanOwner1!' },
  rentalOther: { username: 'e2e_rental_other', password: 'E2eRentalOther1!' },
  reviewUser: { username: 'e2e_review_user', password: 'E2eReviewUser1!' },
  rentalOwner: { username: 'e2e_rental_owner', password: 'E2eRentalOwner1!' },
  reschedUser: { username: 'e2e_resched_user', password: 'E2eReschedUser1!' },
  segOther: { username: 'e2e_seg_other', password: 'E2eSegOther1!' },
  segOwner: { username: 'e2e_seg_owner', password: 'E2eSegOwner1!' },
  splitOwner: { username: 'e2e_split_owner', password: 'E2eSplitOwner1!' },
  splitSpouse: { username: 'e2e_split_spouse', password: 'E2eSplitSpouse1!' },
  stayOther: { username: 'e2e_stay_other', password: 'E2eStayOther1!' },
  stayOwner: { username: 'e2e_stay_owner', password: 'E2eStayOwner1!' },
  trashUser: { username: 'e2e_trash_user', password: 'E2eTrashUser1!' },
  trustGuest: { username: 'e2e_trust_guest', password: 'E2eTrustGuest1!' },
  trustOwner: { username: 'e2e_trust_owner', password: 'E2eTrustOwner1!' },
} satisfies Record<string, E2EAccount>;

export const ALL_ACCOUNTS: E2EAccount[] = [E2E_BROWSER, ...Object.values(ACCOUNTS)];
