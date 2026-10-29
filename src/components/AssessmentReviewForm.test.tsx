import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AssessmentReviewForm,
  assessmentReviewOutcomes,
  validateAssessmentReviewNote,
  type AssessmentReviewOutcome,
} from './AssessmentReviewForm';

afterEach(cleanup);

function renderForm(overrides: Partial<{
  outcome: AssessmentReviewOutcome;
  note: string;
  saving: boolean;
  onOutcomeChange: (outcome: AssessmentReviewOutcome) => void;
  onNoteChange: (note: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}> = {}) {
  const initial = {
    outcome: 'information_requested' as AssessmentReviewOutcome,
    note: '',
    saving: false,
    ...overrides,
  };
  const onOutcomeChange = vi.fn();
  const onNoteChange = vi.fn();
  const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
  function ControlledForm() {
    const [outcome, setOutcome] = useState(initial.outcome);
    const [note, setNote] = useState(initial.note);
    return <AssessmentReviewForm
      outcome={outcome}
      note={note}
      saving={initial.saving}
      onOutcomeChange={value => { onOutcomeChange(value); setOutcome(value); }}
      onNoteChange={value => { onNoteChange(value); setNote(value); }}
      onSubmit={onSubmit}
    />;
  }
  render(<ControlledForm />);
  return { onOutcomeChange, onNoteChange, onSubmit };
}

describe('AssessmentReviewForm', () => {
  it('offers every supported review outcome', () => {
    renderForm();
    const decision = screen.getByRole('combobox', { name: 'Decision' });
    expect((decision as HTMLSelectElement).value).toBe('information_requested');
    expect(screen.getAllByRole('option')).toHaveLength(assessmentReviewOutcomes.length);
    for (const outcome of assessmentReviewOutcomes) {
      expect((screen.getByRole('option', { name: outcome.label }) as HTMLOptionElement).value).toBe(outcome.value);
    }
  });

  it('requires a non-whitespace note and limits it to 2,000 characters', () => {
    renderForm();
    const note = screen.getByRole('textbox', { name: 'Reviewer note' });
    expect((note as HTMLTextAreaElement).required).toBe(true);
    expect((note as HTMLTextAreaElement).maxLength).toBe(2000);
    expect((screen.getByRole('button', { name: 'Record decision' }) as HTMLButtonElement).disabled).toBe(true);
    expect(validateAssessmentReviewNote('  \n  ')).toBe('Add a reviewer note before recording this decision.');
    expect(validateAssessmentReviewNote('Reviewed the source excerpt.')).toBeNull();
  });

  it('notifies the parent when the reviewer selects an outcome and enters a note', async () => {
    const user = userEvent.setup();
    const props = renderForm();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Decision' }), 'evidence_accepted');
    await user.type(screen.getByRole('textbox', { name: 'Reviewer note' }), 'Evidence matches the cited record.');
    expect(props.onOutcomeChange).toHaveBeenLastCalledWith('evidence_accepted');
    expect(props.onNoteChange).toHaveBeenLastCalledWith('Evidence matches the cited record.');
    expect((screen.getByRole('button', { name: 'Record decision' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('submits a complete form once when the reviewer records a decision', async () => {
    const user = userEvent.setup();
    const props = renderForm({ note: 'Please provide a legible source.' });
    await user.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('disables form controls while a submission is in progress', async () => {
    const user = userEvent.setup();
    const props = renderForm({ note: 'Decision note.', saving: true });
    const submit = screen.getByRole('button', { name: 'Saving…' });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('combobox', { name: 'Decision' }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole('textbox', { name: 'Reviewer note' }) as HTMLTextAreaElement).disabled).toBe(true);
    await user.click(submit);
    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it('can submit through the form keyboard interaction', () => {
    const props = renderForm({ note: 'Reviewed using keyboard.' });
    fireEvent.submit(screen.getByRole('textbox', { name: 'Reviewer note' }).closest('form')!);
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });
});
