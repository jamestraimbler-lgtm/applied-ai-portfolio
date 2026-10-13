--!strict
-- Engine-independent round ledger. Only the server owns this state.
local Round = {}
Round.__index = Round

export type State = {
	id: number,
	alive: {[number]: boolean},
	ended: boolean,
	rewarded: {[number]: boolean},
	wave: number,
	warningOpen: boolean,
	bonusEnabled: boolean,
	bonusCollected: {[number]: boolean},
}

function Round.new(id: number, entrants: {number}): State
	local alive = {}
	for _, userId in entrants do alive[userId] = true end
	return {id = id, alive = alive, ended = false, rewarded = {}, wave = 0,
		warningOpen = false, bonusEnabled = false, bonusCollected = {}}
end

function Round.count(state: State): number
	local count = 0
	for _, alive in state.alive do if alive then count += 1 end end
	return count
end

function Round.eliminate(state: State, userId: number): boolean
	if state.ended or not state.alive[userId] then return false end
	state.alive[userId] = false
	state.bonusCollected[userId] = nil
	return true
end

function Round.beginWave(state: State, wave: number, bonusEnabled: boolean): boolean
	if state.ended or wave ~= state.wave + 1 or wave > 6 then return false end
	if state.wave > 0 and not state.rewarded[state.wave] then return false end
	state.wave = wave
	state.warningOpen = true
	state.bonusEnabled = bonusEnabled
	state.bonusCollected = {}
	return true
end

function Round.collectBonus(state: State, userId: number, wave: number): boolean
	if state.ended or not state.warningOpen or not state.bonusEnabled or wave ~= state.wave
		or not state.alive[userId] or state.bonusCollected[userId] then return false end
	state.bonusCollected[userId] = true
	return true
end

function Round.closeWarning(state: State, wave: number)
	if wave == state.wave then state.warningOpen = false end
end

function Round.rewardWave(state: State, wave: number): {[number]: number}
	local awards = {}
	if state.ended or state.rewarded[wave] or wave ~= state.wave or state.warningOpen then return awards end
	state.rewarded[wave] = true
	for userId, alive in state.alive do
		if alive then awards[userId] = 10 + (state.bonusCollected[userId] and 5 or 0) end
	end
	return awards
end

function Round.finish(state: State, completed: boolean): {[number]: number}
	local awards = {}
	if state.ended then return awards end
	state.ended = true
	state.warningOpen = false
	if completed then
		for userId, alive in state.alive do if alive then awards[userId] = 25 end end
	end
	return awards
end

return Round
