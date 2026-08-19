import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/svelte'
import App from './App.svelte'

describe('App', () => {
  it('renders the evidence-bound product title', () => {
    const { getByText } = render(App)
    expect(getByText('Soccer Tactics Agent')).toBeTruthy()
  })
})
