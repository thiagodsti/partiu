"""Trip organizer: a route of cities, movable per-day plan items, and a to-do list.

  domain.py      - PlanStop, PlanItem, PlanTask + allowed statuses
  dto.py         - request/response models
  repository.py  - SQL for trip_plan_stops / trip_plan_items / trip_plan_tasks
  service.py     - access checks, validation, and keeping the trip in step
  routes.py      - /api/trips/{trip_id}/plan...

The board itself (flights, ground legs, stays, day notes) is read by the
frontend from the features that own those rows; this package stores only what
planning adds. See migration 0040.
"""

from .service import planner_service

__all__ = ["planner_service"]
