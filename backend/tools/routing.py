from typing import Optional

from backend.schemas import RoutingTarget


def fallback_route_for_category(
    category: str, subcategory: Optional[str] = None
) -> RoutingTarget:
    if category == "street_flooding":
        return RoutingTarget(
            department="Department of Environmental Protection",
            agency="NYC DEP",
            service="Sewer or catch basin flooding inspection",
            source="demo fallback route",
            confidence=0.74 if subcategory == "near_school_crossing" else 0.62,
        )

    if category == "street_cleanliness":
        return RoutingTarget(
            department="Department of Sanitation",
            agency="NYC DSNY",
            service="Street cleanliness or missed collection review",
            source="demo fallback route",
            confidence=0.7 if subcategory == "trash_bags_on_street" else 0.58,
        )

    return RoutingTarget(
        department="NYC311",
        agency="NYC311",
        service="General service request review",
        source="demo fallback route",
        confidence=0.35,
    )
