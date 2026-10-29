import type { FormEvent } from 'react';

export const assessmentReviewOutcomes = [
  { value: 'evidence_accepted', label: 'Accept evidence' },
  { value: 'evidence_rejected', label: 'Reject evidence' },
  { value: 'information_requested', label: 'Request additional information' },
  { value: 'further_investigation', label: 'Mark for further investigation' },
] as const;

export type AssessmentReviewOutcome = (typeof assessmentReviewOutcomes)[number]['value'];

type AssessmentReviewFormProps = {
  outcome: AssessmentReviewOutcome;
  note: string;
  saving: boolean;
  onOutcomeChange: (outcome: AssessmentReviewOutcome) => void;
  onNoteChange: (note: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function validateAssessmentReviewNote(note: string): string | null {
  return note.trim() ? null : 'Add a reviewer note before recording this decision.';
}

export function AssessmentReviewForm({
  outcome,
  note,
  saving,
  onOutcomeChange,
  onNoteChange,
  onSubmit,
}: AssessmentReviewFormProps) {
  return (
    <form className="application-form assessment-review-form" onSubmit={onSubmit}>
      <label htmlFor="assessment-outcome">Decision<select
        id="assessment-outcome"
        value={outcome}
        disabled={saving}
        onChange={event => onOutcomeChange(event.target.value as AssessmentReviewOutcome)}
      >
        {assessmentReviewOutcomes.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
      <label htmlFor="assessment-note">Reviewer note<textarea
        id="assessment-note"
        aria-describedby="assessment-note-help"
        required
        maxLength={2000}
        disabled={saving}
        value={note}
        onChange={event => onNoteChange(event.target.value)}
      /></label>
      <small id="assessment-note-help" className="assessment-note-help">Required. Add the reason or requested follow-up (up to 2,000 characters). {note.length}/2000</small>
      <button className="button primary" type="submit" disabled={saving || !note.trim()}>
        {saving ? 'Saving…' : 'Record decision'}
      </button>
    </form>
  );
}
