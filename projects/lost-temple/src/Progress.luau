--!strict
-- Monotonic records: merging retries or concurrent servers cannot erase unlocks.
local Progress = {}
type Key = {id:string,tier:string,item:string,goal:string}
type Quest = {key:string,name:string,rune:string,runeName:string,hazard:string,trial:string,region:string,effect:string,requiredStage:number,mode:string}
-- Six one-time expedition keys. Each has one guaranteed relic; there are no paid rolls or duplicates.
Progress.keys = {
 {id="stone_floor",tier="common",item="sand",goal="Survive Crumbling Floor"},
 {id="stone_master",tier="common",item="moss",goal="Survive 3 traps in one run"},
 {id="wind_shrine",tier="rare",item="zephyr",goal="Restore the Wind Shrine"},
 {id="wind_master",tier="rare",item="storm",goal="Survive all 6 traps in one run"},
 {id="sun_lens",tier="epic",item="solar",goal="Restore the Sun Lens"},
 {id="sun_heart",tier="epic",item="eclipse",goal="Recover the Temple Heart"},
}
Progress.tiers = {
 {key="common",name="Common",title="Stone Reliquary",color={198,180,135}},
 {key="rare",name="Rare",title="Wind Reliquary",color={112,195,235}},
 {key="epic",name="Epic",title="Sun Reliquary",color={193,137,247}},
}
export type Record = {best: number, unlocked: {[string]: boolean}, stage: number, cleared: {[string]: boolean}, runes: {[string]: boolean}, keys: {[string]: boolean}, claims: {[string]: boolean}, expedition: any?}
function Progress.clean(value: any): Record
	local result: Record = {best = 0, unlocked = {}, stage = 0, cleared = {}, runes = {}, keys = {}, claims = {}}
	if type(value) ~= "table" then return result end
	if type(value.best) == "number" and value.best == value.best then
		result.best = math.clamp(math.floor(value.best), 0, 6)
	end
	if type(value.unlocked) == "table" then
		for _, key in {"mint", "ice", "coral"} do
			if value.unlocked[key] == true then result.unlocked[key] = true end
		end
	end
	if type(value.stage) == "number" and value.stage == value.stage then result.stage = math.clamp(math.floor(value.stage), 0, 3) end
	local function flags(source: any, keys: {string}): {[string]: boolean}
		local clean: {[string]: boolean} = {}
		if type(source) == "table" then
			for _, key in keys do if source[key] == true then clean[key] = true end end
		end
		return clean
	end
	result.cleared = flags(value.cleared, {"floor", "laser", "meteor", "bonus"})
	result.runes = flags(value.runes, {"steps", "gym", "antenna"})
	if value.unlocked and type(value.unlocked) == "table" and value.unlocked.relic == true
		and result.stage == 3 and result.runes.steps and result.runes.gym and result.runes.antenna then result.unlocked.relic = true end
	for _,key in Progress.keys do
		if type(value.keys)=="table" and value.keys[key.id]==true then result.keys[key.id]=true end
		if type(value.claims)=="table" and value.claims[key.id]==true and result.keys[key.id] then
			result.claims[key.id]=true;result.unlocked[key.item]=true
		end
	end
	result.expedition = type(value.expedition)=="table" and value.expedition or nil
	return result
end
function Progress.merge(old: any, incoming: any): Record
	local result = Progress.clean(old)
	local safe = Progress.clean(incoming)
	-- Economy snapshots never overwrite committed balances; only Rewards transactions mutate them.
	if not result.expedition or safe.expedition and (tonumber(safe.expedition.revision) or 0)>(tonumber(result.expedition.revision) or 0) then result.expedition=safe.expedition end
	result.best = math.max(result.best, safe.best)
	result.stage = math.max(result.stage, safe.stage)
	for key in safe.unlocked do result.unlocked[key] = true end
	for key in safe.cleared do result.cleared[key] = true end
	for key in safe.runes do result.runes[key] = true end
	for key in safe.keys do result.keys[key] = true end
	for key in safe.claims do result.claims[key] = true end
	return result
end
-- Derive earned milestones from authoritative progression, including older saves.
function Progress.keyMilestones(record: Record): {[string]: boolean}
 return {
  stone_floor=record.cleared.floor==true, stone_master=record.best>=3,
  wind_shrine=record.stage>=2, wind_master=record.best>=6,
  sun_lens=record.stage>=3, sun_heart=record.unlocked.relic==true,
 }
end
function Progress.nextKey(record: Record,tier: string): Key?
 for _,key in Progress.keys do
  if key.tier==tier and record.keys[key.id] and not record.claims[key.id] then return key end
 end
 return nil
end
function Progress.keyCount(record: Record,tier: string): number
 local count=0
 for _,key in Progress.keys do
  if key.tier==tier and record.keys[key.id] and not record.claims[key.id] then count+=1 end
 end
 return count
end
function Progress.openChest(record: Record,tier: string): string?
 local key=Progress.nextKey(record,tier)
 if not key then return nil end
 record.claims[key.id]=true;record.unlocked[key.item]=true
 return key.item
end
function Progress.earned(shifts: number, won: boolean, bonuses: number): {[string]: boolean}
	local result = {}
	if shifts >= 3 then result.mint = true end
	if won then result.ice = true end
	if bonuses >= 3 then result.coral = true end
	return result
end
-- Stable record keys preserve the old private prototype's saved progress.
-- One quest definition drives server gates and client instructions.
Progress.mechanisms = {
 {key="causeway", name="Causeway Winch", rune="steps", runeName="Stone Rune", hazard="floor", mode="explorer", trial="Crumbling Floor", region="beneath the courtyard steps", effect="opens the crossing to the Wind Sanctuary", requiredStage=0},
 {key="wind", name="Wind Shrine", rune="gym", runeName="Wind Rune", hazard="laser", mode="sweeping_log", trial="Sweeping Log", region="beyond the sanctuary hurdles", effect="opens the ancient stair to the Sun Gallery", requiredStage=1},
 {key="sun", name="Sun Lens", rune="antenna", runeName="Sun Rune", hazard="meteor", mode="falling_rubble", trial="Falling Rubble", region="beside the Sun Gallery mural", effect="opens the Temple Heart chamber", requiredStage=2},
}
function Progress.runeQuest(key: string): Quest?
 for _,quest in Progress.mechanisms do if quest.rune==key then return quest end end
 return nil
end
function Progress.canCollectRune(record: Record, key: string): boolean
 local q=Progress.runeQuest(key)
 return q~=nil and record.stage>=q.requiredStage and record.cleared[q.hazard]==true and not record.runes[key]
end
-- Repairs are permanent and idempotent. Runes remain in the journal after installation.
function Progress.canRepair(record: Record, key: string?): boolean
 local q=Progress.mechanisms[record.stage+1]
 if not q or (key~=nil and key~=q.key) then return false end
 return record.cleared[q.hazard]==true and record.runes[q.rune]==true and (q.key~="sun" or record.cleared.bonus==true)
end
function Progress.runeCount(record: Record): number
 local count=0
 for _,key in {"steps","gym","antenna"} do if record.runes[key] then count+=1 end end
 return count
end
function Progress.canVault(record: Record): boolean
 return record.stage==3 and Progress.runeCount(record)==3
end
-- This next action drives the journal, recommended trial, compass and world guide.
function Progress.nextAction(record: Record): any
 local q=Progress.mechanisms[record.stage+1]
 if not q then
  for _,missing in Progress.mechanisms do if not record.runes[missing.rune] then q=missing;break end end
 end
 if q then
  if not record.cleared[q.hazard] then return {kind="trial",mode=q.mode,target="TrialGate",title=q.trial,text="PLAY TRIALS → "..string.upper(q.trial).." • survive 3 waves to read the "..q.runeName} end
  if not record.runes[q.rune] then return {kind="rune",target="Rune_"..q.rune,title=q.runeName,text="RECOVER "..string.upper(q.runeName).." • follow the arrows • hold E / tap its prompt"} end
  if q.key=="sun" and not record.cleared.bonus then return {kind="trial",mode="falling_rubble",target="TrialGate",title="Falling Rubble",text="SUN SHARD • start Falling Rubble, collect a gold shard and survive its wave"} end
  return {kind="repair",target="Repair_"..q.key,title=q.name,text="RESTORE "..string.upper(q.name).." • follow the arrows and install the "..q.runeName}
 end
 if not record.unlocked.relic then return {kind="heart",target="VaultPortal",title="Temple Heart",text="TEMPLE HEART OPEN • enter the courtyard doorway and claim the gem"} end
 return {kind="complete",target="TrialGate",title="More challenges",text="TEMPLE HEART RECOVERED • try harder floor challenges for rarer keys"}
end
function Progress.fromPlayer(player: any): Record
 local record=Progress.clean({stage=player:GetAttribute("StationStage") or 0})
 for _,q in Progress.mechanisms do record.cleared[q.hazard]=player:GetAttribute("Cleared_"..q.hazard)==true;record.runes[q.rune]=player:GetAttribute("Rune_"..q.rune)==true end
 record.cleared.bonus=player:GetAttribute("Cleared_bonus")==true
 record.unlocked.relic=player:GetAttribute("Own_relic")==true
 return record
end
function Progress.objective(record: Record): string
 return Progress.nextAction(record).text
end
-- Sparse walking network follows the causeway, hurdle side aisle and gallery stair.
-- Numeric coordinates keep navigation testable without the Roblox engine.
function Progress.routePoints(from: {number}, to: {number}): {{number}}
 local nodes={{0,13.15,79},{0,13.15,88},{24,13.15,88},{39,13.15,88},{60,13.15,88},{56,13.15,83},{56,13.15,51},{68,13.15,51},{68,13.15,88},{68,13.15,96},{68,13.15,110},{40,19.82,110},{12,26.49,110},{-16,33.15,110},{-32,33.15,117},{-22,13.15,88},{-32,13.15,91},{21,13.15,65},{0,13.15,60}}
 local edges={{1,2},{2,3},{3,4},{4,5},{5,6},{6,7},{7,8},{5,9},{9,10},{10,11},{11,12},{12,13},{13,14},{14,15},{2,16},{16,17},{1,18},{1,19},{18,19}}
 local function distance(a: {number},b: {number}): number return math.sqrt((a[1]-b[1])^2+(a[2]-b[2])^2+(a[3]-b[3])^2) end
 local function candidates(p: {number}): {number}
  if p[2]>29 and p[1]<-12 then return {14,15} end
  if p[3]>103 and p[1]>-17 then return {11,12,13,14} end
  if p[1]>49 then
   if p[3]<56 then return {7,8} end
   if p[3]<81 then return {6,7} end
   return {5,6,9,10}
  end
  if p[1]<-25 and p[3]>86 then return {17} end
  if p[3]<72 then return {18,19} end
  if p[1]>17 then return {3,4,18} end
  return {1,2,16,19}
 end
 local function nearest(p: {number}): number
  local best,score=1,math.huge
  for _,i in candidates(p) do local d=distance(p,nodes[i]);if d<score then best=i;score=d end end
  return best
 end
 local first,last=nearest(from),nearest(to)
 local costs: {[number]: number}={[first]=0};local previous: {[number]: number}={};local visited: {[number]: boolean}={}
 for _=1,#nodes do
  local current=nil;local score=math.huge
  for i,d in costs do if not visited[i] and d<score then current=i;score=d end end
  if not current or current==last then break end
  visited[current]=true
  for _,e in edges do
   local nextNode=e[1]==current and e[2] or e[2]==current and e[1] or nil
   if nextNode then local d=score+distance(nodes[current],nodes[nextNode]);if d<(costs[nextNode] or math.huge) then costs[nextNode]=d;previous[nextNode]=current end end
  end
 end
 local route={};local cursor: number?=last
 while cursor do table.insert(route,1,nodes[cursor]);cursor=previous[cursor] end
 table.insert(route,to)
 -- Once close to the destination, do not send the player back to a network node.
 if first==last and distance(from,to)<12 then return {to} end
 if #route>1 and distance(from,route[1])<4 then table.remove(route,1) end
 return route
end
return Progress
