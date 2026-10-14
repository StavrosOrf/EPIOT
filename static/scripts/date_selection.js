// Send local calendar dates, never UTC ISO conversions of picker midnights.
export function calendarDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// Scenarios are synthetic and generated on request, so past and future dates are
// equally valid; `minDate` is optional and there is no "today" limit.
export function pickerOptions(rangeMode, minDate, today, selectedDates, onChange) {
  const valid = selectedDates.filter(date => !minDate || calendarDate(date) >= calendarDate(minDate));
  const dates = valid.length ? valid : [today];
  return {
    mode: rangeMode ? "range" : "single", minDate: minDate || null, maxDate: null,
    dateFormat: "Y-m-d", defaultDate: rangeMode ? [dates[0], dates.at(-1)] : dates.at(-1),
    disableMobile: true, onChange,
  };
}
