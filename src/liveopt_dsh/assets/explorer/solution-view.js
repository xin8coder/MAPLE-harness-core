(function (root) {
  "use strict";
  const record = (value) =>
    value && typeof value === "object" && !Array.isArray(value);

  function presentSolution(raw = {}) {
    const result = { ...raw };
    // Preserve original downloads. These aliases only adapt explicit result
    // fields for the charts; no schedules or business values are inferred.
    if (
      !Array.isArray(raw.order_plan) &&
      Array.isArray(raw.orders) &&
      raw.orders.length &&
      raw.orders.every(
        (row) =>
          record(row) &&
          (row.id != null || row.order_id != null) &&
          Number.isFinite(row.start_hour) &&
          Number.isFinite(row.finish_hour ?? row.pack_finish_hour),
      )
    ) {
      result.order_plan = raw.orders.map((row) => {
        const out = { ...row, order_id: row.order_id ?? row.id,
          finish_hour: row.finish_hour ?? row.pack_finish_hour };
        const arrival =
          row.arrival_hour ?? row.delivery_hour ?? row.arrive_hour;
        const late = row.late_hours ?? row.lateness_hours ?? row.overdue_hours ?? row.tardiness_hours;
        if (row.team_id != null && out.team == null) out.team = row.team_id;
        if (row.assigned_zone != null && out.warehouse == null) out.warehouse = row.assigned_zone;
        if (row.carton_count != null && out.cartons == null) out.cartons = row.carton_count;
        if (arrival != null) out.arrival_hour = arrival;
        if (late != null) out.late_hours = late;
        delete out.id;
        delete out.delivery_hour;
        delete out.arrive_hour;
        delete out.lateness_hours;
        delete out.pack_finish_hour;
        delete out.overdue_hours;
        delete out.tardiness_hours;
        delete out.team_id;
        delete out.assigned_zone;
        delete out.carton_count;
        return out;
      });
      delete result.orders;
    }
    const teamRows = Array.isArray(raw.teams)
      ? raw.teams.map((row) => [row?.team ?? row?.team_id, row])
      : record(raw.teams) ? Object.entries(raw.teams) : [];
    if (
      !Array.isArray(raw.worker_shifts) &&
      teamRows.length &&
      teamRows.every(
        ([id, row]) => id != null && record(row) && Number.isFinite(row.workers ?? row.headcount),
      )
    ) {
      result.worker_shifts = teamRows.map(([id, row]) => ({
        ...row,
        team: row.team ?? id,
        workers: row.workers ?? row.headcount,
        ...(Number.isFinite(row.overtime_hours ?? row.team_overtime_hours)
          ? { overtime_hours: row.overtime_hours ?? row.team_overtime_hours } : {}),
      }));
      delete result.teams;
    }
    const warehouses = raw.warehouses ?? raw.zones;
    const warehouseRows = Array.isArray(warehouses)
      ? warehouses.map((row) => [row?.warehouse ?? row?.zone_id, row])
      : record(warehouses) ? Object.entries(warehouses) : [];
    if (
      !Array.isArray(raw.warehouse_plan) &&
      warehouseRows.length &&
      warehouseRows.every(
        ([id, row]) =>
          id != null && record(row) &&
          Number.isFinite(row.capacity ?? row.capacity_cartons) &&
          Number.isFinite(row.used ?? row.cartons ?? row.used_cartons),
      )
    ) {
      result.warehouse_plan = warehouseRows.map(
        ([id, row]) => {
          const out = {
            ...row,
            warehouse: row.warehouse ?? id,
            used: row.used ?? row.cartons ?? row.used_cartons,
            capacity: row.capacity ?? row.capacity_cartons,
          };
          delete out.cartons;
          delete out.used_cartons;
          delete out.zone_id;
          delete out.capacity_cartons;
          return out;
        },
      );
      delete result.warehouses;
      delete result.zones;
    }
    return result;
  }

  if (typeof module === "object" && module.exports)
    module.exports = { presentSolution };
  else root.MAPLESolutionView = { presentSolution };
})(typeof globalThis !== "undefined" ? globalThis : this);
