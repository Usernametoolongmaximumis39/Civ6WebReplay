-----------------------------------------------
-- SWITZERLAND FUNCTIONS
-- Author: ChimpanG
-----------------------------------------------

-----------------------------------------------
-- UTILITIES
-----------------------------------------------

function C15_ValidTrait(sTrait)
    local tValid = {}
    for k, v in ipairs(PlayerManager.GetWasEverAliveIDs()) do
        local leaderType = PlayerConfigurations[v]:GetLeaderTypeName()
        for trait in GameInfo.LeaderTraits() do
            if trait.LeaderType == leaderType and trait.TraitType == sTrait then 
                tValid[v] = true 
            end;
        end
        if not tValid[v] then
            local civType = PlayerConfigurations[v]:GetCivilizationTypeName()
            for trait in GameInfo.CivilizationTraits() do
                if trait.CivilizationType == civType and trait.TraitType == sTrait then 
                    tValid[v] = true 
                end;
            end
        end
    end
    return tValid
end

-----------------------------------------------
-- VARIABLES
-----------------------------------------------

	local sTrait = "TRAIT_CIVILIZATION_CVS_SWITZERLAND_UA"
	local tTraitPlayers = C15_ValidTrait(sTrait)

--[[
	local tEras = {}
	local tEraQuery = DB.Query("SELECT DISTINCT EraType FROM Eras")
	for k, v in ipairs(tEraQuery) do
		tEras[GameInfo.Eras[v.EraType].Index] = true
	end

	local tTechs = {}
	local tTechQuery = DB.Query("SELECT DISTINCT TechnologyType FROM Technologies")
	for k, v in ipairs(tTechQuery) do
		tTechs[GameInfo.Technologies[v.TechnologyType].Index] = true
	end

	local tCivics = {}
	local tCivicQuery = DB.Query("SELECT DISTINCT CivicType FROM Civics")
	for k, v in ipairs(tCivicQuery) do
		tCivics[GameInfo.Civics[v.CivicType].Index] = true
	end
--]]

-----------------------------------------------
-- FUNCTION CPG_Switzerland_GovernorEnvoy
-- Credits: ChimpanG
-----------------------------------------------

function CPG_Switzerland_GovernorEnvoy(playerID, governorID, promotionID)
	
	print("playerID is ", playerID)
	print("governorID is ", governorID)
	print("promotionID is ", promotionID)

	if tTraitPlayers[playerID] then -- Check player trait
		print("Player has trait")	
		
		local iPlayer = Players[playerID]		
		iPlayer:GetInfluence():ChangeTokensToGive(1) -- grant envoy
		print ("Envoy granted")
	end

	print ("CPG_Switzerland_GovernorEnvoy Complete!")
end		

-- Events.GovernorPromoted.Add(CPG_Switzerland_GovernorEnvoy);

-----------------------------------------------
-- FUNCTION CPG_Switzerland_CivicBoostEraScore
-- Credits: ChimpanG
-----------------------------------------------

function CPG_Switzerland_CivicBoostEraScore(playerID, iBoostedCivic, iUnknownA, iUnknownB)
	
	print("playerID is ", playerID)
	print("iBoostedCivic is ", iBoostedTech)
	print("iUnknownA is ", iUnknownA)
	print("iUnknownB is ", iUnknownB)

	if tTraitPlayers[playerID] then -- Check player trait
		print("Player has trait")

		local iPlayer = Players[playerID]
		local pPlayerCities = iPlayer:GetCities()
		local pCapital = pPlayerCities:GetCapitalCity()
		local pCity = pPlayerCities:FindID(pCapital)

		Game.ChangePlayerEraScore(playerID, 1) -- Grant +1 Era Score

		if iPlayer:IsHuman() then
			Game.AddWorldViewText(playerID, Locale.Lookup("+{1_Num} [ICON_Glory_Golden_Age] Era Score", 1), pCity:GetX(), pCity:GetY(), 0)
		end
	end

	print ("CPG_Switzerland_CivicBoostEraScore Complete!")
end		

-- Events.CivicBoostTriggered.Add(CPG_Switzerland_CivicBoostEraScore);

